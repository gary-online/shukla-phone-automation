# CLAUDE.md — Shukla Phone Automation

## Project Overview
AI-powered phone answering service for Shukla Surgical Support's PPS department. Twilio ConversationRelay → FastAPI WebSocket → Claude API → structured outputs (CSV, Google Chat, Email).

## Tech Stack
- Python 3.13 (pyenv), FastAPI, uvicorn
- Anthropic SDK (`AsyncAnthropic` — always use async client)
- Twilio Voice + ConversationRelay (WebSocket-based STT/TTS)
- Gmail API (OAuth2), Google Chat webhooks, CSV output
- Pydantic v2 for data models

## Key Conventions
- **Async everywhere**: All I/O in async functions. Sync libraries (Gmail API) must use `run_in_executor()`.
- **StrEnum for enums**: Use `enum.StrEnum`, not `(str, Enum)`. Python 3.13 `str()` on `(str, Enum)` returns `ClassName.MEMBER` instead of the value.
- **Tool use pattern**: Claude extracts structured data via `submit_call_record` tool_use, not free-text parsing.
- **PHI protection**: The system prompt instructs Claude to never capture patient identifying information. Tests verify this.

## Running
```bash
source .venv/bin/activate
python -m src.main                        # Start server
python -m src.test.test_claude_prompt     # Run Claude prompt tests
```

## Project Structure
- `src/main.py` — FastAPI app, HTTP routes (`/voice/incoming`, `/voice/status`), WebSocket (`/ws/conversation`)
- `src/config.py` — Env var loading (Twilio, Anthropic, Google, server settings)
- `src/types.py` — `RequestType`, `Priority` (StrEnum), `CallRecord`, `CallRecordExtract` (Pydantic), `TRAY_CATALOG` (22 tray types)
- `src/system_prompt.py` — Claude system prompt with domain knowledge, conversation flow, PHI rules
- `src/claude_service.py` — `AsyncAnthropic` client, `get_claude_response()`, tool definition + handling
- `src/websocket_handler.py` — `CallSession` state, ConversationRelay message handling (setup, prompt, interrupt, dtmf, error)
- `src/call_processor.py` — `process_completed_call()` dispatches CSV + Chat + Email in parallel via `asyncio.gather()`
- `src/csv_service.py` — Appends to monthly CSV files in `data/`
- `src/google_chat_service.py` — Posts card messages to Google Chat webhook
- `src/email_service.py` — Sends email via Gmail API (sync calls wrapped in executor)
- `src/test/test_claude_prompt.py` — Integration tests requiring a live API key

## Environment Variables
See `.env.example` for all required/optional variables. Required: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `ANTHROPIC_API_KEY`.
