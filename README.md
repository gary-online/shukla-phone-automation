# Shukla Phone Automation

AI-powered phone answering service for Shukla Surgical Support's PPS (Pay Per Surgery) department. Receives calls from sales reps, has a natural conversation via AI, extracts structured data, and delivers it via email, Google Chat, and CSV.

## How It Works

1. **Sales rep calls** the Twilio phone number
2. **Twilio ConversationRelay** handles speech-to-text and text-to-speech (via Google)
3. **Claude AI** has a natural conversation, collecting case details (rep name, request type, tray types, surgeon, facility, surgery date)
4. **Structured data is extracted** using Claude's tool_use (not free-text parsing)
5. **Results are delivered** in parallel: email notification, Google Chat message, and CSV record

```
Phone Call → Twilio (STT/TTS) → FastAPI WebSocket → Claude AI → Email + Chat + CSV
```

## Quick Start

### Prerequisites

- Python 3.13
- A Twilio account with a phone number
- An Anthropic API key (or OpenRouter key)
- ngrok for local development

### Installation

```bash
git clone https://github.com/gary-online/shukla-phone-automation.git
cd shukla-phone-automation
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Required
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_PHONE_NUMBER=+1234567890
ANTHROPIC_API_KEY=your_key

# Optional: Use OpenRouter instead of direct Anthropic
ANTHROPIC_BASE_URL=https://openrouter.ai/api
CLAUDE_MODEL=anthropic/claude-haiku-4-5-20251001

# Optional: Gmail notifications
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_secret
GOOGLE_REFRESH_TOKEN=your_refresh_token
GMAIL_FROM_ADDRESS=you@gmail.com
GMAIL_TO_ADDRESS=team@example.com

# Optional: Google Chat notifications
GOOGLE_CHAT_WEBHOOK_URL=https://chat.googleapis.com/v1/spaces/...

# Server
PORT=8080
HOST=0.0.0.0
BASE_URL=https://your-domain.ngrok-free.dev
```

### Running Locally

**1. Start the server:**
```bash
source .venv/bin/activate
python -m src.main
```

**2. Start ngrok (in another terminal):**
```bash
ngrok http 8080
# Or with a static domain:
ngrok http --url=your-domain.ngrok-free.dev 8080
```

**3. Configure Twilio:**
- Go to console.twilio.com → Phone Numbers → your number
- Set Voice webhook URL to: `https://your-domain.ngrok-free.dev/voice/incoming` (POST)
- Or set it programmatically — the server logs the correct URL on startup

**4. Make a test call** to your Twilio number from a verified phone number.

### Running Tests

```bash
# All unit tests (no API key needed)
pytest src/test/ -v

# Integration tests only (needs ANTHROPIC_API_KEY)
python -m src.test.test_claude_prompt
```

## What the AI Handles

| Request Type | What It Collects |
|-------------|-----------------|
| PPS Case Report | Rep name, surgeon, facility, tray types, surgery date |
| Bill Only Request | Rep name, surgeon, facility, trays used |
| FedEx Label Request | Rep name, destination, tray type |
| Tray Availability | Rep name, tray type needed |
| Delivery Status | Rep name, order/tracking details |
| Other | Rep name, details of request |

The AI knows 22 surgical tray types from the Shukla catalog and can identify them by name.

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/voice/incoming` | POST | Twilio voice webhook — returns ConversationRelay TwiML |
| `/voice/status` | POST | Call status callbacks (optional) |
| `/ws/conversation` | WebSocket | Twilio ConversationRelay real-time conversation |
| `/health` | GET | Detailed health check with subsystem status |
| `/health/live` | GET | Simple liveness probe |
| `/health/ready` | GET | Readiness probe (503 if Claude API unreachable) |

## Output Formats

### Email
```
Subject: [New] Bill Only Request — Gary

New Bill Only Request
========================================

Timestamp: 2026-03-13T14:34:44+00:00
Rep Name: Gary
Request Type: Bill Only Request
Tray Type: Maxi, Mini, Blade
Surgeon: Dr. John Smith
Facility: Cast Hospital 1
Surgery Date: 2026-03-20

Priority: NORMAL
Call SID: CA0313a...
```

### CSV
Monthly files in `data/call-records-YYYY-MM.csv` with columns:
`call_sid, timestamp, rep_name, request_type, tray_type, surgeon, facility, surgery_date, details, priority, routed_to, call_duration_seconds`

### Google Chat
Card-formatted messages with conditional fields posted to the configured webhook.

## Privacy & PHI Protection

- The AI is instructed to **never capture patient identifying information** (names, DOB, SSN, MRN)
- Conversation history is **in-memory only** — not persisted to disk
- Call recordings are **not stored**
- Integration tests verify PHI protection

## Tech Stack

- **Python 3.13** + **FastAPI** + **uvicorn**
- **Anthropic SDK** (AsyncAnthropic) for Claude AI
- **Twilio** Voice + ConversationRelay for phone handling
- **Google APIs** for Gmail (OAuth2) and Chat (webhooks)
- **Pydantic v2** for data validation

## Project Status

See [PLAN.md](PLAN.md) for the full development roadmap and current phase checklist.
