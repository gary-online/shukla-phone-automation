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
| AI | Claude API (Haiku 4.5, upgradeable to Sonnet) | Conversation + structured data extraction via tool_use |
| Backend | Python 3.13 + FastAPI | WebSocket handler, business logic, integrations |
| Output: Email | Gmail API (OAuth2) | Send structured case reports |
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
- Anthropic API key
- (Optional) Google Workspace API credentials for Gmail
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
python -m src.test.test_claude_prompt     # Run Claude prompt tests
```

### Twilio Configuration
1. Buy a phone number in Twilio Console
2. Set the Voice webhook URL to: `https://your-server/voice/incoming` (POST)
3. Set the Status callback URL to: `https://your-server/voice/status` (POST)
4. For local development, use ngrok: `ngrok http 8080`

### Google Chat Webhook
1. Open the Google Chat space
2. Apps & integrations → Webhooks → Create
3. Copy the webhook URL to `GOOGLE_CHAT_WEBHOOK_URL` in `.env`

### Gmail API Setup
1. Create OAuth2 credentials in Google Cloud Console
2. Enable Gmail API
3. Generate a refresh token
4. Add credentials to `.env`

## Development Phases

- [x] Phase 1: Foundation — FastAPI server, WebSocket endpoint for ConversationRelay
- [x] Phase 2: Conversations — Claude integration with system prompt, request type detection, confirmation flow, `submit_call_record` tool_use
- [x] Phase 3: Outputs — CSV (monthly files), Google Chat (webhook cards), Gmail (OAuth2 email)
- [x] Phase 3.5: Bug fixes — AsyncAnthropic, StrEnum for Python 3.13, event loop safety
- [ ] Phase 4: Polish & testing — PHI protection verification, edge cases, internal team testing
- [ ] Phase 5: Production deployment — Cloud Run, Dockerfile, monitoring

### Phase 4 Checklist
- [ ] Fill `.env` with Twilio + Anthropic credentials
- [ ] Run Claude prompt tests (`python -m src.test.test_claude_prompt`)
- [ ] Iterate on system prompt based on test results
- [ ] PHI filtering verification (test with patient-like data)
- [ ] Edge case handling (bad audio, interruptions, unknown requests)
- [ ] Start server + ngrok, configure Twilio webhook
- [ ] Make first test call end-to-end
- [ ] Set up Google Chat webhook and Gmail API credentials
- [ ] Internal team testing with real sales reps

### Phase 5 Checklist
- [ ] Choose hosting (Google Cloud Run recommended)
- [ ] Add Dockerfile
- [ ] Set up monitoring and error alerting
- [ ] Go live with dedicated Twilio number
- [ ] Gather feedback and iterate

### Future: Epicor/Kinetic Integration
- Connect structured call data to Epicor API
- Auto-create quotes from PPS case reports
- Trigger Bill Only creation on shuklamedical.com frontend

## File Structure

```
src/
  main.py               — FastAPI server, routes, WebSocket endpoint
  config.py             — Environment variable loading
  types.py              — Pydantic models (StrEnum), tray catalog (22 types), request types
  system_prompt.py      — Claude system prompt with domain knowledge + PHI rules
  claude_service.py     — AsyncAnthropic client, submit_call_record tool_use
  websocket_handler.py  — Twilio ConversationRelay WebSocket handler
  call_processor.py     — Post-call dispatch (CSV + Chat + Email in parallel)
  csv_service.py        — Monthly CSV file output
  google_chat_service.py — Google Chat webhook card notifications
  email_service.py      — Gmail API email sender (async-safe via executor)
  test/
    test_claude_prompt.py — 3 integration tests: PPS case, PHI protection, FedEx label
```

## Decisions

- **Language**: Python 3.13 + FastAPI (not Node.js)
- **AI**: Custom build with Twilio + Claude (not 3CX, Retell AI, or SIP server)
- **Claude client**: AsyncAnthropic (non-blocking in FastAPI's event loop)
- **Enums**: StrEnum (Python 3.11+) — `str()` returns the value, not `ClassName.MEMBER`
- **Existing phone system**: RingCentral (unchanged, separate from this project)
- **No Dockerfile yet** — deployment is Phase 5
