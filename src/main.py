import logging
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from twilio.twiml.voice_response import VoiceResponse

from src.config import ADMIN_API_KEY, BASE_URL, HOST, PORT, ENV
from src.error_history import get_recent_errors
from src.logging_config import setup_logging
from src.websocket_handler import handle_conversation_relay

setup_logging(ENV)
logger = logging.getLogger(__name__)

app = FastAPI(title="Shukla Surgical Support - AI Phone Service")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    from datetime import datetime, timezone

    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/voice/incoming")
async def voice_incoming(request: Request):
    """Twilio webhook for incoming voice calls.

    Returns TwiML that connects the call to ConversationRelay via WebSocket.
    """
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
    if api_key != ADMIN_API_KEY:
        return Response(status_code=401)
    return {"errors": get_recent_errors()}


@app.post("/voice/status")
async def voice_status(request: Request):
    """Twilio webhook for call status callbacks (optional, for logging)."""
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
