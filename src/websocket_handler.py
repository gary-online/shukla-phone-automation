import asyncio
import json
import logging
import time

from fastapi import WebSocket, WebSocketDisconnect

from src.claude_service import ClaudeResponse, ConversationTurn, get_claude_response
from src.call_processor import process_completed_call
from src.health import active_sessions

logger = logging.getLogger(__name__)

MAX_HISTORY = 20


class CallSession:
    def __init__(self):
        self.call_sid: str = ""
        self.conversation_history: list[ConversationTurn] = []
        self.start_time: float = time.time()
        self.call_record_submitted: bool = False
        self.should_close: bool = False
        self.last_assistant_response: str = ""
        self.escalation_sent: bool = False
        self.turn_count: int = 0
        self.claude_latencies: list[float] = []
        self.request_type: str = ""

    def trim_history(self) -> None:
        """Keep first turn + last (MAX_HISTORY - 1) turns to stay within limits."""
        if len(self.conversation_history) <= MAX_HISTORY:
            return
        self.conversation_history = (
            self.conversation_history[:1] + self.conversation_history[-(MAX_HISTORY - 1):]
        )


async def _get_response_with_filler(
    ws: WebSocket,
    session: CallSession,
) -> ClaudeResponse:
    """Get Claude response, sending a filler message if it takes too long."""
    response_task = asyncio.create_task(get_claude_response(session.conversation_history))

    async def _send_filler():
        await asyncio.sleep(2.5)
        if not response_task.done():
            await _send_text_response(ws, "One moment please.")

    filler_task = asyncio.create_task(_send_filler())

    try:
        response = await response_task
    finally:
        filler_task.cancel()
        try:
            await filler_task
        except asyncio.CancelledError:
            pass

    return response


async def handle_conversation_relay(ws: WebSocket) -> None:
    await ws.accept()
    session = CallSession()
    session_id = id(session)
    active_sessions.add(session_id)
    logger.info("New ConversationRelay WebSocket connection")

    try:
        while not session.should_close:
            data = await ws.receive_text()
            message = json.loads(data)
            await _handle_message(ws, session, message)
    except WebSocketDisconnect:
        duration = int(time.time() - session.start_time)
        avg_latency = int(sum(session.claude_latencies) / len(session.claude_latencies) * 1000) if session.claude_latencies else 0
        max_latency = int(max(session.claude_latencies) * 1000) if session.claude_latencies else 0
        logger.info(
            "Call ended: call_sid=%s duration=%ds turns=%d record_submitted=%s "
            "request_type=%s avg_claude_ms=%d max_claude_ms=%d",
            session.call_sid, duration, session.turn_count,
            session.call_record_submitted, session.request_type or "none",
            avg_latency, max_latency,
        )
    except Exception as e:
        duration = int(time.time() - session.start_time)
        avg_latency = int(sum(session.claude_latencies) / len(session.claude_latencies) * 1000) if session.claude_latencies else 0
        max_latency = int(max(session.claude_latencies) * 1000) if session.claude_latencies else 0
        logger.error(
            "Call error: call_sid=%s duration=%ds turns=%d record_submitted=%s "
            "request_type=%s avg_claude_ms=%d max_claude_ms=%d error=%s",
            session.call_sid, duration, session.turn_count,
            session.call_record_submitted, session.request_type or "none",
            avg_latency, max_latency, e,
        )
    finally:
        active_sessions.discard(session_id)


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

        session.trim_history()
        greeting = await get_claude_response(session.conversation_history)
        session.conversation_history.append(
            ConversationTurn(role="assistant", content=greeting.text)
        )

        await _send_text_response(ws, greeting.text)
        session.last_assistant_response = greeting.text

    elif msg_type == "prompt":
        caller_speech = message.get("voicePrompt", "")
        if not caller_speech:
            return

        logger.info("Caller speech (call_sid=%s): %s", session.call_sid, caller_speech)

        session.conversation_history.append(
            ConversationTurn(role="user", content=caller_speech)
        )

        session.trim_history()
        start = time.time()
        response = await _get_response_with_filler(ws, session)
        session.claude_latencies.append(time.time() - start)
        session.turn_count += 1
        session.conversation_history.append(
            ConversationTurn(role="assistant", content=response.text)
        )

        await _send_text_response(ws, response.text)
        session.last_assistant_response = response.text

        if response.transfer_reason and not session.escalation_sent:
            session.escalation_sent = True
            session.should_close = True
            from src.email_service import send_escalation_email
            from datetime import datetime, timezone
            await send_escalation_email(
                call_sid=session.call_sid,
                rep_name="",
                reason=response.transfer_reason,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        if response.call_record:
            session.request_type = str(response.call_record.request_type)

        # If Claude used the submit tool, process the call record
        if response.call_record and not session.call_record_submitted:
            session.call_record_submitted = True
            duration = int(time.time() - session.start_time)
            await process_completed_call(session.call_sid, response.call_record, duration)

    elif msg_type == "interrupt":
        logger.debug("Caller interrupted (call_sid=%s)", session.call_sid)

    elif msg_type == "dtmf":
        digit = message.get("digit", "")
        logger.info("DTMF received (call_sid=%s): %s", session.call_sid, digit)

        if digit == "0":
            session.should_close = True
            await _send_text_response(
                ws,
                "I'm going to have one of our team members follow up with you directly. Thank you for calling.",
            )
            if not session.escalation_sent:
                session.escalation_sent = True
                from src.email_service import send_escalation_email
                from datetime import datetime, timezone
                await send_escalation_email(
                    call_sid=session.call_sid,
                    rep_name="",
                    reason="Caller pressed 0 to speak with a human",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
        elif digit == "*":
            text = session.last_assistant_response or "I haven't said anything yet."
            await _send_text_response(ws, text)

    elif msg_type == "error":
        logger.error("ConversationRelay error (call_sid=%s): %s", session.call_sid, message)

    else:
        logger.warning("Unknown message type (call_sid=%s): %s", session.call_sid, msg_type)


async def _send_text_response(ws: WebSocket, text: str) -> None:
    await ws.send_text(
        json.dumps({"type": "text", "token": text, "last": True})
    )
