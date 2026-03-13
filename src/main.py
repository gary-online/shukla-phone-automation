import asyncio
import hmac
import logging
import signal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import VoiceResponse

from src.config import ADMIN_API_KEY, BASE_URL, HOST, PORT, ENV, TWILIO_AUTH_TOKEN
from src.error_history import get_recent_errors
from src.health import active_sessions, check_claude_api, check_csv_dir, check_gmail
from src.logging_config import setup_logging
from src.websocket_handler import handle_conversation_relay

setup_logging(ENV)
logger = logging.getLogger(__name__)

app = FastAPI(title="Shukla Surgical Support - AI Phone Service")

_twilio_validator = RequestValidator(TWILIO_AUTH_TOKEN)

# Initialized in on_startup when the event loop is running
_shutdown_event: asyncio.Event | None = None


@app.on_event("startup")
async def on_startup():
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: _shutdown_event.set())

    # Validate required services
    logger.info("Validating services...")

    claude_check = await check_claude_api()
    if claude_check["status"] != "ok":
        logger.error("Claude API check failed: %s", claude_check["status"])
        # Don't crash — might be a temporary issue, let health checks report it
        logger.warning("Starting with degraded Claude API — calls may fail")
    else:
        logger.info("Claude API: OK (latency=%dms)", claude_check["latency_ms"])

    gmail_check = check_gmail()
    if gmail_check["status"] == "configured":
        logger.info("Gmail API: configured")
    else:
        logger.info("Gmail API: not configured (email notifications disabled)")

    csv_check = check_csv_dir()
    if csv_check.get("writable"):
        logger.info("CSV directory: writable")
    else:
        logger.warning("CSV directory: %s", csv_check["status"])

    logger.info("Startup validation complete")


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Shutdown initiated, waiting for %d active calls...", len(active_sessions))
    for _ in range(30):
        if not active_sessions:
            break
        await asyncio.sleep(1)
    if active_sessions:
        logger.warning("Force-closing %d remaining sessions", len(active_sessions))
    logger.info("Shutdown complete")


@app.get("/health")
async def health():
    from datetime import datetime, timezone

    claude = await check_claude_api()
    return {
        "status": "ok" if claude["status"] == "ok" else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "claude_api": claude,
            "gmail": check_gmail(),
            "csv_dir": check_csv_dir(),
            "active_calls": len(active_sessions),
        },
    }


@app.get("/health/live")
async def health_live():
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready():
    if _shutdown_event and _shutdown_event.is_set():
        return Response(
            content='{"status": "shutting down"}',
            status_code=503,
            media_type="application/json",
        )
    claude = await check_claude_api()
    if claude["status"] != "ok":
        return Response(
            content='{"status": "not ready", "reason": "claude_api unreachable"}',
            status_code=503,
            media_type="application/json",
        )
    return {"status": "ready"}


async def _validate_twilio(request: Request) -> None:
    """Validate that the request comes from Twilio using signature verification.

    In production (ENV=production), invalid signatures are rejected with 403.
    In development, invalid signatures are logged as warnings but allowed through,
    because ngrok URL rewriting causes legitimate signature mismatches.
    """
    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)
    body = dict(await request.form())
    if not _twilio_validator.validate(url, body, signature):
        if ENV == "production":
            logger.warning("Invalid Twilio signature for %s", url)
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")
        logger.debug("Twilio signature mismatch (expected in dev with ngrok)")


@app.post("/voice/incoming")
async def voice_incoming(request: Request):
    """Twilio webhook for incoming voice calls.

    Returns TwiML that connects the call to ConversationRelay via WebSocket.
    """
    await _validate_twilio(request)

    twiml = VoiceResponse()
    connect = twiml.connect()

    ws_host = urlparse(BASE_URL).hostname
    connect.conversation_relay(
        url=f"wss://{ws_host}/ws/conversation",
        voice="Google.en-US-Journey-F",
        transcription_provider="google",
        tts_provider="google",
        language="en-US",
    )

    logger.info("Incoming call — returned ConversationRelay TwiML")
    return Response(content=str(twiml), media_type="text/xml")


@app.websocket("/ws/conversation")
async def ws_conversation(ws: WebSocket):
    """WebSocket endpoint for Twilio ConversationRelay."""
    await handle_conversation_relay(ws)


@app.get("/errors")
async def errors(request: Request):
    if not ADMIN_API_KEY:
        return Response(status_code=404)
    api_key = request.headers.get("X-API-Key", "")
    if not hmac.compare_digest(api_key, ADMIN_API_KEY):
        return Response(status_code=401)
    return {"errors": get_recent_errors()}


@app.post("/voice/status")
async def voice_status(request: Request):
    """Twilio webhook for call status callbacks (optional, for logging)."""
    await _validate_twilio(request)

    body = await request.form()
    logger.info(
        "Call status update: call_sid=%s status=%s duration=%s",
        body.get("CallSid"),
        body.get("CallStatus"),
        body.get("CallDuration"),
    )
    return {"received": True}


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting server on %s:%s", HOST, PORT)
    logger.info("Voice webhook: %s/voice/incoming", BASE_URL)
    logger.info("WebSocket endpoint: %s/ws/conversation", BASE_URL)
    uvicorn.run(app, host=HOST, port=PORT)
