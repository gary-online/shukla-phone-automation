import json
import logging
import time

from fastapi import WebSocket, WebSocketDisconnect

from src.claude_service import ConversationTurn, stream_claude_response
from src.call_processor import process_completed_call
from src.types import CallRecordExtract

logger = logging.getLogger(__name__)


class CallSession:
    def __init__(self):
        self.call_sid: str = ""
        self.conversation_history: list[ConversationTurn] = []
        self.start_time: float = time.time()
        self.call_record_submitted: bool = False


async def handle_conversation_relay(ws: WebSocket) -> None:
    await ws.accept()
    session = CallSession()
    logger.info("New ConversationRelay WebSocket connection")

    try:
        while True:
            data = await ws.receive_text()
            message = json.loads(data)
            await _handle_message(ws, session, message)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected (call_sid=%s)", session.call_sid)
    except Exception as e:
        logger.error("WebSocket error (call_sid=%s): %s", session.call_sid, e)


async def _handle_message(
    ws: WebSocket,
    session: CallSession,
    message: dict,
) -> None:
    msg_type = message.get("type", "")

    if msg_type == "setup":
        session.call_sid = message.get("callSid", "")
        logger.info("Call setup received: call_sid=%s", session.call_sid)

        # Send initial greeting via Claude
        session.conversation_history.append(
            ConversationTurn(role="user", content="[Call connected. The caller just dialed in. Greet them.]")
        )

        full_text, call_record = await _stream_response(ws, session)
        session.conversation_history.append(
            ConversationTurn(role="assistant", content=full_text)
        )

    elif msg_type == "prompt":
        caller_speech = message.get("voicePrompt", "")
        if not caller_speech:
            return

        logger.info("Caller speech (call_sid=%s): %s", session.call_sid, caller_speech)

        session.conversation_history.append(
            ConversationTurn(role="user", content=caller_speech)
        )

        full_text, call_record = await _stream_response(ws, session)
        session.conversation_history.append(
            ConversationTurn(role="assistant", content=full_text)
        )

        # If Claude used the submit tool, process the call record
        if call_record and not session.call_record_submitted:
            session.call_record_submitted = True
            duration = int(time.time() - session.start_time)
            await process_completed_call(session.call_sid, call_record, duration)

    elif msg_type == "interrupt":
        logger.debug("Caller interrupted (call_sid=%s)", session.call_sid)

    elif msg_type == "dtmf":
        logger.debug("DTMF received (call_sid=%s): %s", session.call_sid, message.get("digit"))

    elif msg_type == "error":
        logger.error("ConversationRelay error (call_sid=%s): %s", session.call_sid, message)

    else:
        logger.warning("Unknown message type (call_sid=%s): %s", session.call_sid, msg_type)


async def _stream_response(
    ws: WebSocket,
    session: CallSession,
) -> tuple[str, CallRecordExtract | None]:
    """Stream Claude's response to the caller via ConversationRelay tokens.

    Returns the full text and optional call record.
    """
    full_text = ""
    call_record = None

    async for chunk in stream_claude_response(session.conversation_history):
        if isinstance(chunk, CallRecordExtract):
            call_record = chunk
        elif isinstance(chunk, str):
            full_text += chunk
            # Send each sentence as a token with last=False so TTS starts immediately
            await ws.send_text(json.dumps({
                "type": "text",
                "token": chunk,
                "last": False,
            }))

    # Send final empty token with last=True to signal end of response
    await ws.send_text(json.dumps({
        "type": "text",
        "token": "",
        "last": True,
    }))

    return full_text, call_record
