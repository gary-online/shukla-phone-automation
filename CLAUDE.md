# CLAUDE.md — Shukla Phone Automation

## Project Overview
AI-powered phone answering service for Shukla Surgical Support's PPS department. Twilio ConversationRelay → FastAPI WebSocket → Claude API → structured outputs (CSV, Google Chat, Email).

## Tech Stack
- Python 3.13 (pyenv), FastAPI, uvicorn
- Anthropic SDK (`AsyncAnthropic` — always use async client)
- Twilio Voice + ConversationRelay (WebSocket-based STT/TTS via Google)
- Gmail API (OAuth2), Google Chat webhooks, CSV output
- Pydantic v2 for data models
- OpenRouter as API proxy (configurable, direct Anthropic also supported)

## Key Conventions
- **Async everywhere**: All I/O in async functions. Sync libraries (Gmail API) must use `run_in_executor()`.
- **StrEnum for enums**: Use `enum.StrEnum`, not `(str, Enum)`. Python 3.13 `str()` on `(str, Enum)` returns `ClassName.MEMBER` instead of the value.
- **Tool use pattern**: Claude extracts structured data via `submit_call_record` tool_use, not free-text parsing. A second tool `transfer_to_human` handles escalation.
- **PHI protection**: The system prompt instructs Claude to never capture patient identifying information. Tests verify this.
- **Error handling**: All external calls (Claude API, Gmail, Google Chat, CSV writes) have try/except with specific error types. Failures in output services don't block each other (`asyncio.gather` with `return_exceptions=True`).
- **Retry with backoff**: Transient failures retry via `src/retry.py` utility (exponential backoff). Applied to Claude API, Gmail, Google Chat.
- **Timeouts**: Claude API 30s, Google Chat 10s, Gmail 15s. No hanging calls.
- **Structured logging**: JSON in production, human-readable in development. Every log includes `call_sid` for tracing.

## Running
```bash
source .venv/bin/activate
python -m src.main                        # Start server
pytest src/test/                          # Run all tests
python -m src.test.test_claude_prompt     # Run Claude prompt integration tests (needs API key)
```

## Testing
```bash
pytest src/test/ -v                       # All unit tests (no API key needed)
pytest src/test/test_claude_prompt.py     # Integration tests (needs ANTHROPIC_API_KEY)
```

## Project Structure
```
src/
  main.py               — FastAPI server, routes, health checks, graceful shutdown
  config.py             — Environment variable loading with validation
  types.py              — RequestType, Priority (StrEnum), CallRecord, CallRecordExtract, TRAY_CATALOG
  system_prompt.py      — Claude system prompt with domain knowledge, conversation flow, PHI rules
  claude_service.py     — AsyncAnthropic client, streaming, tool definitions (submit_call_record, transfer_to_human)
  websocket_handler.py  — CallSession state, ConversationRelay message handling, DTMF, silence filler
  call_processor.py     — Post-call dispatch (CSV + Chat + Email in parallel)
  csv_service.py        — Monthly CSV file output with error handling
  google_chat_service.py — Google Chat webhook card notifications
  email_service.py      — Gmail API email sender + escalation emails
  retry.py              — Async retry with exponential backoff utility
  logging_config.py     — Structured logging (JSON prod, readable dev)
  test/
    test_claude_prompt.py        — Integration tests (live API)
    test_retry.py                — Retry utility tests
    test_csv_service.py          — CSV write/append/error tests
    test_email_service.py        — Email formatting tests
    test_google_chat_service.py  — Chat card formatting tests
    test_call_processor.py       — Dispatch + partial failure tests
    test_websocket_handler.py    — WebSocket flow tests
    test_claude_service.py       — Tool parsing + validation tests
    test_types.py                — StrEnum + Pydantic tests
```

## Environment Variables
See `.env.example` for all required/optional variables. Required: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `ANTHROPIC_API_KEY`.

## Endpoints
- `POST /voice/incoming` — Twilio voice webhook, returns ConversationRelay TwiML
- `POST /voice/status` — Call status callbacks (optional)
- `WS /ws/conversation` — Twilio ConversationRelay WebSocket
- `GET /health` — Detailed health check (Claude API, Gmail, CSV dir, active calls)
- `GET /health/live` — Simple liveness probe
- `GET /health/ready` — Readiness probe (503 if Claude unreachable or shutting down)
- `GET /errors` — Recent errors (requires `X-API-Key` header, set `ADMIN_API_KEY`)

## Design Docs
- `docs/superpowers/specs/2026-03-13-app-hardening-design.md` — Full design spec for hardening + production readiness
