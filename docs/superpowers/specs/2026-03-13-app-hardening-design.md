# App Hardening & Production Readiness Design

## Overview

Comprehensive improvement of the Shukla Phone Automation service across four layers: core hardening, call quality, observability, and production readiness. No rewrites — targeted improvements to the existing clean codebase.

## Layer 1: Core Hardening

### Error Handling

**claude_service.py:**
- Wrap `json.loads(tool_input_json)` in try/except `JSONDecodeError`. On failure, log warning with the raw JSON string and return a response with no call_record (conversation continues normally).
- If tool input is parsed but `rep_name` or `request_type` is empty/missing, log warning and skip record submission.

**csv_service.py:**
- Wrap file open/write in try/except `OSError`. Log error with full path and record details. Raise so `process_completed_call` captures it via `return_exceptions=True`.

**email_service.py:**
- Wrap `_get_gmail_service()` and `.send()` in try/except. Catch `google.auth.exceptions.RefreshError` separately (token expired) vs general `HttpError`. Log specific error type.
- Remove silent swallowing — let exceptions propagate to `process_completed_call`.

**google_chat_service.py:**
- Wrap httpx POST in try/except `httpx.HTTPError`. Log error with status code and response body.

### Timeouts

- Claude API: 30s timeout via `timeout=httpx.Timeout(30.0)` on the AsyncAnthropic client constructor.
- Google Chat webhook: 10s timeout on httpx POST.
- Gmail send: 15s timeout via `asyncio.wait_for()` wrapping the executor call.

### Retry Logic

New utility: `src/retry.py`
```python
async def with_retry(coro_fn, max_attempts=3, base_delay=1.0, max_delay=10.0):
    """Retry async callable with exponential backoff.

    Retries on Exception (excluding ValueError, KeyError, TypeError).
    Returns result on success, raises last exception on exhaustion.
    """
```

Applied to:
- Claude API: retry wraps the entire `get_claude_response()` function. If the first stream succeeds but the follow-up (closing message after tool use) fails, the retry restarts from scratch. To prevent double-submission, `process_completed_call()` is only called after `get_claude_response()` returns successfully — retries are invisible to the caller.
- Gmail send (2 attempts, 2s base delay)
- Google Chat POST (2 attempts, 1s base delay)

**Pydantic ValidationError handling:** Catch `pydantic.ValidationError` (a `ValueError` subclass) when constructing `CallRecordExtract`. On failure, log the raw tool input and return a `ClaudeResponse` with no `call_record` — same as the `JSONDecodeError` path. This runs before retry would apply, so no conflict.

### Conversation Safety

- Cap `conversation_history` at 20 turns in `CallSession`. When exceeded, keep the first turn (greeting context) and the last 18 turns. Test: at turn 21, verify history has 19 entries with the first turn preserved.
- Validate tool input: `rep_name` must be non-empty, `request_type` must be a valid `RequestType` enum value. If invalid, log and skip.

## Layer 2: Call Quality

### Interrupt Handling

**websocket_handler.py:**
- On "interrupt" message, set `session.interrupted = True`.
- When the next "prompt" arrives after an interrupt, the caller's new speech takes priority (current behavior already works this way since we process each prompt sequentially — just add logging).

### Human Escalation

**New tool: `transfer_to_human`**

Schema:
```json
{
  "name": "transfer_to_human",
  "description": "Transfer the caller to a human when you cannot help, the caller requests it, or the situation requires human judgment.",
  "input_schema": {
    "type": "object",
    "properties": {
      "reason": {"type": "string", "description": "Why the transfer is needed"}
    },
    "required": ["reason"]
  }
}
```

Behavior:
- When Claude calls this tool, send a polite message to the caller ("I'm going to have one of our team members follow up with you directly. Thank you for calling.")
- Log the escalation with reason and call_sid at WARNING level.
- Send escalation email via new `send_escalation_email(call_sid, rep_name, reason, timestamp)` function in `email_service.py`. This is separate from `send_email_notification()` since there's no complete `CallRecord`. Subject: `[ESCALATION] Call from {rep_name or "unknown"} — {reason}`.
- End the session: set `session.should_close = True` flag on `CallSession`. The WebSocket message loop in `handle_conversation_relay()` checks this flag after each `_handle_message()` call and breaks the loop, allowing the `finally` block to run cleanup and log the call summary.

**System prompt addition:**
```
If the caller asks to speak to a person, becomes frustrated, or you cannot fulfill their request, use the transfer_to_human tool with a brief reason. Do not try to force the conversation to continue.
```

### DTMF Actions

- `0` → trigger transfer_to_human (reason: "Caller pressed 0 to speak with a human")
- `*` → resend the last assistant response via TTS (stored in `CallSession.last_assistant_response: str = ""`; updated after each Claude response; if empty, send "I haven't said anything yet.")

### Conversation Flow Improvements

**System prompt updates:**
- Add: "Keep each response to 1-2 sentences. Be concise — the caller is on a phone, not reading a screen."
- Add: "If the caller says goodbye, thank you, or indicates they're done without completing a record, say goodbye warmly. Do not force data collection."

**Silence handling:**
- After sending caller speech to Claude, start a 2.5-second timer. If no response received, send "One moment please" to TTS while continuing to wait for the real response.
- Implementation: task-based approach. `asyncio.create_task(get_claude_response(...))` runs the API call. A separate coroutine sleeps 2.5s then sends the filler if the task isn't done yet. `asyncio.shield()` ensures the API call is never cancelled. Once the real response arrives, send it normally. This avoids the `asyncio.wait_for()` cancellation problem.

### Goodbye Without Record

- If WebSocket disconnects and no call_record was submitted, log at INFO level with conversation history summary (first and last 2 turns).
- No forced submission — some calls are just inquiries.

## Layer 3: Observability

### Structured Logging

**New: `src/logging_config.py`**

Replace basic `logging.basicConfig()` with a JSON formatter for structured logs:
```json
{
  "timestamp": "2026-03-13T10:31:49.532Z",
  "level": "INFO",
  "logger": "src.websocket_handler",
  "message": "Caller speech received",
  "call_sid": "CA0313a...",
  "data": {"speech_length": 42}
}
```

In development (detected by `ENV=development` or absence of `ENV`), use human-readable format:
```
2026-03-13 10:31:49 INFO [CA0313a] Caller speech received (42 chars)
```

**CallSession gets a logger adapter** that auto-includes `call_sid` in every log message.

### Key Events Logged

| Event | Level | Data |
|-------|-------|------|
| Call connected | INFO | call_sid |
| Greeting sent | INFO | call_sid, response_ms, text_length |
| Caller speech | INFO | call_sid, speech_length, turn_number |
| Claude response | INFO | call_sid, response_ms, text_length, turn_number |
| Tool submission | INFO | call_sid, request_type, rep_name |
| Tool validation failed | WARNING | call_sid, raw_input |
| Output success (CSV/Chat/Email) | INFO | call_sid, service_name |
| Output failure | ERROR | call_sid, service_name, error_type, error_detail |
| Human escalation | WARNING | call_sid, reason |
| Call ended | INFO | call_sid, duration_s, turn_count, record_submitted |
| API timeout | ERROR | call_sid, service, timeout_s |
| Retry attempt | WARNING | call_sid, service, attempt, delay_s |

### Call Metrics

At call end, log a single structured JSON summary:
```json
{
  "event": "call_summary",
  "call_sid": "CA...",
  "duration_seconds": 174,
  "turn_count": 8,
  "record_submitted": true,
  "request_type": "Bill Only Request",
  "outputs": {"csv": "success", "email": "success", "chat": "skipped"},
  "avg_claude_latency_ms": 1200,
  "max_claude_latency_ms": 2100
}
```

### Error History Endpoint

**GET /errors** — Returns last 50 errors from an in-memory ring buffer. Protected by a simple API key header (`X-API-Key`) configured via `ADMIN_API_KEY` env var. Returns 401 if missing/invalid. If `ADMIN_API_KEY` is not set, endpoint is disabled (returns 404).
```json
{
  "errors": [
    {
      "timestamp": "...",
      "call_sid": "CA...",
      "service": "email",
      "error": "HttpError 403: accessNotConfigured",
      "resolved": false
    }
  ]
}
```

Implementation: simple `collections.deque(maxlen=50)` in a module-level variable. No database needed.

## Layer 4: Production Readiness

### Dockerfile

```dockerfile
FROM python:3.13-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.13-slim
WORKDIR /app
RUN useradd -r -s /bin/false appuser
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ src/
RUN mkdir -p /app/data
# NOTE: data/ must be volume-mounted in production to persist CSV records
# e.g., docker run -v /host/data:/app/data ...
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8080/health || exit 1
CMD ["python", "-m", "src.main"]
```

### Graceful Shutdown

**main.py:**
- Register SIGTERM/SIGINT handlers.
- On signal: set a shutdown flag, stop accepting new WebSocket connections, wait up to 30 seconds for active calls to finish.
- After 30 seconds, explicitly cancel any remaining session tasks. The `WebSocketDisconnect` / `CancelledError` handlers in `handle_conversation_relay()` run cleanup and log the call summary.
- Track active sessions in a set. WebSocket handler adds/removes sessions.

### Enhanced Health Check

**GET /health** returns:
```json
{
  "status": "ok",
  "timestamp": "...",
  "checks": {
    "claude_api": {"status": "ok", "latency_ms": 250},
    "gmail": {"status": "ok"},
    "csv_dir": {"status": "ok", "writable": true},
    "active_calls": 2
  }
}
```

- Claude API: cached ping (check every 60 seconds, not every request). Uses a minimal `messages.create` with prompt `"ping"` and `max_tokens=1`. Cached result stored in a module-level dict `{"status": ..., "latency_ms": ..., "checked_at": time.time()}`. Between checks, returns cached result. Cost: ~2 tokens per check = negligible.
- Gmail: verify credentials can refresh (cached, check every 5 minutes).
- CSV dir: verify directory exists and is writable.
- Active calls: count of current WebSocket sessions.

**GET /health/live** — simple liveness probe (always returns 200 if server is up).
**GET /health/ready** — readiness probe (returns 503 if Claude API unreachable or shutting down).

### Tests

**Test structure:**
```
src/test/
  test_claude_prompt.py        # existing integration tests
  test_retry.py                # retry utility tests
  test_csv_service.py          # CSV write, append, headers, error handling
  test_email_service.py        # email body formatting, subject lines, priority labels
  test_google_chat_service.py  # card formatting, webhook error handling
  test_call_processor.py       # routing, parallel dispatch, partial failures
  test_websocket_handler.py    # setup → prompt → tool flow with mock WS
  test_claude_service.py       # tool parsing, validation, timeout, malformed JSON
  test_types.py                # StrEnum behavior, Pydantic model validation
```

All new tests use **pytest** with **unittest.mock** — no live API keys needed.

**Key test cases:**
- CSV: write new file with header, append to existing, handle disk error (mock open to raise OSError)
- Email: verify subject format for urgent vs normal, verify body includes all fields, verify missing optional fields handled
- Chat: verify card JSON structure, verify conditional sections (no surgeon = no surgeon field)
- Call processor: mock all 3 services, verify parallel execution, verify one failure doesn't block others
- WebSocket: mock WebSocket, send setup message, send prompt, verify Claude called, verify response sent back
- Claude service: mock streaming response with tool_use, verify CallRecordExtract parsed correctly, inject malformed JSON, verify graceful handling
- Retry: verify exponential backoff timing, verify max attempts, verify success on 2nd attempt
- Types: verify StrEnum str() returns value not class name, verify Pydantic validation
- Transfer to human: DTMF `0` triggers escalation, Claude-triggered escalation, escalation email sent, session closes
- Conversation history truncation: at turn 21, verify 19 entries with first turn preserved, no off-by-one
- Silence filler: mock slow Claude response (>2.5s), verify filler sent AND real response still delivered

### Startup Validation

**main.py on startup:**
1. Verify Claude API key is valid (one lightweight API call).
2. If Gmail configured, verify refresh token works.
3. If Google Chat configured, verify webhook URL is reachable (HEAD request).
4. Verify CSV output directory exists and is writable.
5. Log startup summary: which services are active, which are skipped.

Fail fast on Claude API (required). Warn but continue on optional services.

## Files Modified

| File | Changes |
|------|---------|
| `src/main.py` | Graceful shutdown, enhanced health checks, startup validation, error history endpoint |
| `src/config.py` | Add ENV variable for dev/prod logging, ADMIN_API_KEY |
| `src/claude_service.py` | Timeout, retry, JSON error handling, tool validation, transfer_to_human tool |
| `src/websocket_handler.py` | Interrupt handling, DTMF actions, silence filler, session tracking, call metrics, goodbye handling |
| `src/call_processor.py` | Error logging improvements |
| `src/csv_service.py` | Error handling around file I/O |
| `src/email_service.py` | Error handling, timeout, escalation emails |
| `src/google_chat_service.py` | Error handling, timeout |
| `src/system_prompt.py` | Conciseness instructions, escalation instructions, goodbye handling |
| `src/types.py` | No changes |
| **New files** | |
| `src/retry.py` | Retry with exponential backoff utility |
| `src/logging_config.py` | Structured JSON logging setup |
| `Dockerfile` | Production container |
| `src/test/test_retry.py` | Retry utility tests |
| `src/test/test_csv_service.py` | CSV service tests |
| `src/test/test_email_service.py` | Email service tests |
| `src/test/test_google_chat_service.py` | Chat service tests |
| `src/test/test_call_processor.py` | Call processor tests |
| `src/test/test_websocket_handler.py` | WebSocket handler tests |
| `src/test/test_claude_service.py` | Claude service tests |
| `src/test/test_types.py` | Type/enum tests |

## What This Does NOT Include

- No external monitoring (Sentry, Datadog) — just good logs
- No database — CSV stays as-is
- No Epicor/Kinetic integration — future phase
- No call recording storage
- No multi-tenant support
- No load balancing — single instance is sufficient for current volume
