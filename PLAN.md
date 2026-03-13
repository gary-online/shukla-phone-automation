# AI Phone Answering Service — Shukla Surgical Support

## Overview

Shukla Surgical Support (shuklamedical.com) manufactures surgical implant extraction devices ("trays") and rents them to doctors. The PPS (Pay Per Surgery) department receives ~20+ calls/day from sales reps reporting case details, requesting FedEx labels, Bill Only documents, tray availability, delivery status, and more.

This project builds an AI-powered phone answering system to receive, transcribe, structure, and route this information automatically.

## Architecture

```
Sales Rep calls → Twilio Phone Number → Twilio ConversationRelay (WebSocket)
    → Python Server (FastAPI) → Claude API (structured extraction + conversation)
    → Outputs: Email, Google Chat, CSV, (future: Epicor/Kinetic)
```

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Phone/Voice | Twilio Voice + ConversationRelay | Inbound calls, STT, TTS |
| AI | Claude API (Haiku 4.5 via OpenRouter, upgradeable) | Conversation + structured data extraction via tool_use |
| Backend | Python 3.13 + FastAPI | WebSocket handler, business logic, integrations |
| Output: Email | Gmail API (OAuth2) | Send structured case reports + escalation alerts |
| Output: Chat | Google Chat Webhooks | Notify PPS team |
| Output: CSV | Local file storage | Append structured data (monthly files) |

### Estimated Monthly Cost: ~$110–$230/mo

| Item | Cost |
|------|------|
| Twilio Phone Number | $1.15/mo |
| Twilio Voice (inbound) | ~$19/mo |
| Twilio ConversationRelay (STT+TTS) | ~$66–$110/mo |
| Claude API (Haiku 4.5) | ~$20–$80/mo |
| Cloud Hosting | ~$5–$20/mo |

## Setup

### Prerequisites
- Python 3.13 (via pyenv)
- Twilio account with a phone number
- Anthropic API key (or OpenRouter key)
- (Optional) Google Cloud project with Gmail API enabled
- (Optional) Google Chat webhook URL

### Install & Run
```bash
cd ~/Projects/shukla-phone-automation
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your credentials
python -m src.main                        # Run the server
pytest src/test/ -v                       # Run all tests
```

### Twilio Configuration
1. Buy a phone number in Twilio Console
2. Set the Voice webhook URL to: `https://your-server/voice/incoming` (POST)
3. Set the Status callback URL to: `https://your-server/voice/status` (POST)
4. For local development, use ngrok: `ngrok http 8080`
5. Or use a static ngrok domain: `ngrok http --url=your-domain.ngrok-free.dev 8080`

### Google Chat Webhook
1. Open the Google Chat space
2. Apps & integrations → Webhooks → Create
3. Copy the webhook URL to `GOOGLE_CHAT_WEBHOOK_URL` in `.env`

### Gmail API Setup
1. Create a Google Cloud project at console.cloud.google.com
2. Enable Gmail API (APIs & Services → Library → Gmail API)
3. Create OAuth consent screen (External, add your email as test user)
4. Create OAuth 2.0 credentials (Web application)
5. Add `https://developers.google.com/oauthplayground` as authorized redirect URI
6. Go to developers.google.com/oauthplayground, use your credentials
7. Authorize `https://mail.google.com/` scope, exchange for refresh token
8. Add `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, `GMAIL_FROM_ADDRESS`, `GMAIL_TO_ADDRESS` to `.env`

## Development Phases

- [x] Phase 1: Foundation — FastAPI server, WebSocket endpoint for ConversationRelay
- [x] Phase 2: Conversations — Claude integration with system prompt, request type detection, confirmation flow, `submit_call_record` tool_use
- [x] Phase 3: Outputs — CSV (monthly files), Google Chat (webhook cards), Gmail (OAuth2 email)
- [x] Phase 3.5: Bug fixes — AsyncAnthropic, StrEnum for Python 3.13, event loop safety
- [x] Phase 4a: Live testing — OpenRouter integration, ngrok tunneling, Twilio webhook config, first test calls, Gmail API setup
- [ ] Phase 4b: Hardening — Error handling, timeouts, retries, conversation safety (see design spec)
- [ ] Phase 4c: Call quality — Human escalation tool, DTMF actions, silence filler, system prompt refinement
- [ ] Phase 4d: Observability — Structured logging, call metrics, error endpoint
- [ ] Phase 4e: Tests — Unit tests for all services, WebSocket handler, Claude service, retry utility
- [ ] Phase 5: Production — Dockerfile, graceful shutdown, health checks, startup validation, Cloud Run deployment

### Phase 4b: Hardening Checklist
- [ ] Add try/except around JSON parsing of tool input (JSONDecodeError + Pydantic ValidationError)
- [ ] Add error handling to CSV writes (OSError)
- [ ] Fix email service error swallowing (catch RefreshError, HttpError separately)
- [ ] Add error handling to Google Chat webhook (httpx.HTTPError)
- [ ] Set 30s timeout on Claude API client
- [ ] Set 10s timeout on Google Chat, 15s on Gmail
- [ ] Implement retry utility (src/retry.py) with exponential backoff
- [ ] Apply retry to Claude API (3 attempts), Gmail (2), Google Chat (2)
- [ ] Cap conversation history at 20 turns
- [ ] Validate tool input (non-empty rep_name, valid request_type)

### Phase 4c: Call Quality Checklist
- [ ] Add transfer_to_human tool + system prompt instructions
- [ ] Add escalation email function (send_escalation_email)
- [ ] Add session.should_close flag for graceful session termination
- [ ] Implement DTMF handling (0 = transfer, * = repeat last response)
- [ ] Add session.last_assistant_response tracking
- [ ] Implement 2.5s silence filler (task-based, not asyncio.wait_for)
- [ ] Update system prompt: conciseness, goodbye handling, escalation
- [ ] Log conversation summary on disconnect without record submission

### Phase 4d: Observability Checklist
- [ ] Create src/logging_config.py (JSON prod, readable dev)
- [ ] Add CallSession logger adapter with call_sid
- [ ] Log all key events (see design spec event table)
- [ ] Log structured call summary JSON at call end
- [ ] Add /errors endpoint with ring buffer (protected by ADMIN_API_KEY)
- [ ] Add timing to every Claude API call

### Phase 4e: Test Checklist
- [ ] test_retry.py — backoff timing, max attempts, success on retry
- [ ] test_csv_service.py — write, append, headers, OSError handling
- [ ] test_email_service.py — body formatting, subject lines, priority
- [ ] test_google_chat_service.py — card JSON, conditional sections
- [ ] test_call_processor.py — parallel dispatch, partial failures
- [ ] test_websocket_handler.py — setup→prompt→tool flow, DTMF, escalation, history truncation
- [ ] test_claude_service.py — tool parsing, malformed JSON, ValidationError
- [ ] test_types.py — StrEnum str(), Pydantic validation

### Phase 5 Checklist
- [ ] Create Dockerfile (multi-stage, non-root, volume for data/)
- [ ] Implement graceful shutdown (SIGTERM, 30s drain, cancel stuck sessions)
- [ ] Enhanced health checks (/health, /health/live, /health/ready)
- [ ] Startup validation (Claude API, Gmail, CSV dir)
- [ ] Deploy to Google Cloud Run
- [ ] Set up monitoring and error alerting
- [ ] Go live with dedicated Twilio number

### Future: Epicor/Kinetic Integration
- Connect structured call data to Epicor API
- Auto-create quotes from PPS case reports
- Trigger Bill Only creation on shuklamedical.com frontend

## File Structure

```
src/
  main.py               — FastAPI server, routes, health checks, graceful shutdown
  config.py             — Environment variable loading with validation
  types.py              — Pydantic models (StrEnum), tray catalog (22 types), request types
  system_prompt.py      — Claude system prompt with domain knowledge + PHI rules
  claude_service.py     — AsyncAnthropic client, streaming, tool definitions + handling
  websocket_handler.py  — Twilio ConversationRelay WebSocket handler, DTMF, silence filler
  call_processor.py     — Post-call dispatch (CSV + Chat + Email in parallel)
  csv_service.py        — Monthly CSV file output
  google_chat_service.py — Google Chat webhook card notifications
  email_service.py      — Gmail API email sender + escalation emails
  retry.py              — Async retry with exponential backoff
  logging_config.py     — Structured logging configuration
  test/
    test_claude_prompt.py        — Integration tests (live API)
    test_retry.py                — Retry utility tests
    test_csv_service.py          — CSV service tests
    test_email_service.py        — Email formatting tests
    test_google_chat_service.py  — Chat card formatting tests
    test_call_processor.py       — Dispatch + partial failure tests
    test_websocket_handler.py    — WebSocket flow tests
    test_claude_service.py       — Tool parsing + validation tests
    test_types.py                — StrEnum + Pydantic tests
data/
  call-records-YYYY-MM.csv — Monthly call record files
docs/
  superpowers/specs/     — Design specifications
Dockerfile              — Production container
```

## Decisions

- **Language**: Python 3.13 + FastAPI (not Node.js)
- **AI**: Custom build with Twilio + Claude (not 3CX, Retell AI, or SIP server)
- **API proxy**: OpenRouter for development/testing, direct Anthropic for production
- **Claude client**: AsyncAnthropic (non-blocking in FastAPI's event loop)
- **Enums**: StrEnum (Python 3.11+) — `str()` returns the value, not `ClassName.MEMBER`
- **Existing phone system**: RingCentral (unchanged, separate from this project)
- **Logging**: JSON structured in production, human-readable in development
- **No external monitoring tools** — good structured logs first, add Sentry/Datadog later if needed
