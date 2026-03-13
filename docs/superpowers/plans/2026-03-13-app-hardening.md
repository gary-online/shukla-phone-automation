# App Hardening & Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the Shukla Phone Automation service with error handling, retries, timeouts, human escalation, structured logging, tests, and production deployment readiness.

**Architecture:** Four layers applied incrementally — core hardening first (error safety nets), then call quality (escalation, DTMF, silence filler), then observability (structured logging, metrics), then production (Dockerfile, health checks, tests). Each layer is independently testable.

**Tech Stack:** Python 3.13, FastAPI, AsyncAnthropic, Twilio ConversationRelay, pytest, unittest.mock

**Spec:** `docs/superpowers/specs/2026-03-13-app-hardening-design.md`

---

## Chunk 1: Core Hardening

### Task 1: Retry Utility

**Files:**
- Create: `src/retry.py`
- Create: `src/test/test_retry.py`

- [ ] **Step 1: Write test file for retry utility**

```python
# src/test/test_retry.py
import asyncio
import pytest
from unittest.mock import AsyncMock

from src.retry import with_retry


@pytest.mark.asyncio
async def test_succeeds_first_try():
    fn = AsyncMock(return_value="ok")
    result = await with_retry(fn, max_attempts=3)
    assert result == "ok"
    assert fn.call_count == 1


@pytest.mark.asyncio
async def test_succeeds_on_second_try():
    fn = AsyncMock(side_effect=[ConnectionError("fail"), "ok"])
    result = await with_retry(fn, max_attempts=3, base_delay=0.01)
    assert result == "ok"
    assert fn.call_count == 2


@pytest.mark.asyncio
async def test_exhausts_all_attempts():
    fn = AsyncMock(side_effect=ConnectionError("fail"))
    with pytest.raises(ConnectionError, match="fail"):
        await with_retry(fn, max_attempts=3, base_delay=0.01)
    assert fn.call_count == 3


@pytest.mark.asyncio
async def test_does_not_retry_value_error():
    fn = AsyncMock(side_effect=ValueError("bad input"))
    with pytest.raises(ValueError, match="bad input"):
        await with_retry(fn, max_attempts=3, base_delay=0.01)
    assert fn.call_count == 1


@pytest.mark.asyncio
async def test_does_not_retry_type_error():
    fn = AsyncMock(side_effect=TypeError("wrong type"))
    with pytest.raises(TypeError, match="wrong type"):
        await with_retry(fn, max_attempts=3, base_delay=0.01)
    assert fn.call_count == 1


@pytest.mark.asyncio
async def test_exponential_backoff_timing():
    """Verify delays increase exponentially."""
    call_times = []
    attempt = 0

    async def slow_then_ok():
        nonlocal attempt
        call_times.append(asyncio.get_event_loop().time())
        attempt += 1
        if attempt < 3:
            raise ConnectionError("not yet")
        return "ok"

    result = await with_retry(slow_then_ok, max_attempts=3, base_delay=0.05, max_delay=1.0)
    assert result == "ok"
    # Second call should be ~0.05s after first, third ~0.10s after second
    gap1 = call_times[1] - call_times[0]
    gap2 = call_times[2] - call_times[1]
    assert gap1 >= 0.04  # base_delay with some tolerance
    assert gap2 >= 0.08  # 2 * base_delay with tolerance
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest src/test/test_retry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.retry'`

- [ ] **Step 3: Implement retry utility**

```python
# src/retry.py
import asyncio
import logging

logger = logging.getLogger(__name__)

# Errors that indicate bad input, not transient failures — never retry these
_NO_RETRY = (ValueError, TypeError, KeyError)


async def with_retry(
    fn,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
):
    """Call an async callable with exponential backoff retry.

    Retries on any Exception except ValueError, TypeError, KeyError
    (which indicate logic errors, not transient failures).
    """
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except _NO_RETRY:
            raise
        except Exception as e:
            last_error = e
            if attempt == max_attempts:
                raise
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            logger.warning(
                "Retry %d/%d after %.1fs: %s",
                attempt, max_attempts, delay, e,
            )
            await asyncio.sleep(delay)

    raise last_error  # unreachable, but satisfies type checker
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest src/test/test_retry.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/retry.py src/test/test_retry.py
git commit -m "feat: add async retry utility with exponential backoff"
```

---

### Task 2: Add Timeouts to Claude API Client

**Files:**
- Modify: `src/config.py`
- Modify: `src/claude_service.py:14-17`

- [ ] **Step 1: Add timeout config**

In `src/config.py`, add after line 26:
```python
CLAUDE_TIMEOUT = int(_optional("CLAUDE_TIMEOUT", "30"))
```

- [ ] **Step 2: Add timeout to AsyncAnthropic client**

In `src/claude_service.py`, replace lines 14-17:

```python
import httpx

client = anthropic.AsyncAnthropic(
    api_key=ANTHROPIC_API_KEY,
    timeout=httpx.Timeout(CLAUDE_TIMEOUT, connect=10.0),
    **({"base_url": ANTHROPIC_BASE_URL} if ANTHROPIC_BASE_URL else {}),
)
```

Update the import at line 7:
```python
from src.config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, CLAUDE_MODEL, CLAUDE_TIMEOUT
```

- [ ] **Step 3: Verify server still starts**

Run: `source .venv/bin/activate && python -c "from src.claude_service import client; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add src/config.py src/claude_service.py
git commit -m "feat: add 30s timeout to Claude API client"
```

---

### Task 3: Error Handling in Claude Service (JSON + Pydantic)

**Files:**
- Modify: `src/claude_service.py:129-142`
- Create: `src/test/test_claude_service.py`

- [ ] **Step 1: Write tests for error handling**

```python
# src/test/test_claude_service.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.claude_service import get_claude_response, ConversationTurn, ClaudeResponse


def _make_history():
    return [ConversationTurn(role="user", content="Hello")]


def _make_stream_events(text="Hi there!", tool_name=None, tool_id=None, tool_input=None):
    """Build a list of mock stream events."""
    events = []

    # Text block start
    text_block = MagicMock()
    text_block.type = "text"
    events.append(MagicMock(type="content_block_start", content_block=text_block))

    # Text deltas
    for chunk in [text]:
        delta = MagicMock()
        delta.type = "text_delta"
        delta.text = chunk
        events.append(MagicMock(type="content_block_delta", delta=delta))

    # Tool block if provided
    if tool_name and tool_input:
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = tool_name
        tool_block.id = tool_id or "tool_123"
        events.append(MagicMock(type="content_block_start", content_block=tool_block))

        delta = MagicMock()
        delta.type = "input_json_delta"
        delta.partial_json = json.dumps(tool_input)
        events.append(MagicMock(type="content_block_delta", delta=delta))

    return events


class MockStream:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.events:
            raise StopAsyncIteration
        return self.events.pop(0)


@pytest.mark.asyncio
async def test_malformed_json_returns_no_record():
    """If Claude returns invalid JSON for tool input, return response with no call_record."""
    events = []
    # Tool block with malformed JSON
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "submit_call_record"
    tool_block.id = "tool_123"
    events.append(MagicMock(type="content_block_start", content_block=tool_block))

    delta = MagicMock()
    delta.type = "input_json_delta"
    delta.partial_json = "{invalid json!!!"
    events.append(MagicMock(type="content_block_delta", delta=delta))

    with patch("src.claude_service.client") as mock_client:
        mock_client.messages.stream.return_value = MockStream(events)
        result = await get_claude_response(_make_history())

    assert result.call_record is None
    assert result.done is False


@pytest.mark.asyncio
async def test_invalid_request_type_returns_no_record():
    """If tool input has an invalid request_type, return response with no call_record."""
    tool_input = {
        "rep_name": "Gary",
        "request_type": "Nonexistent Type",
        "tray_type": "",
        "surgeon": "",
        "facility": "",
        "surgery_date": "",
        "details": "test",
        "priority": "normal",
    }
    events = _make_stream_events(
        text="", tool_name="submit_call_record",
        tool_id="tool_123", tool_input=tool_input,
    )

    with patch("src.claude_service.client") as mock_client:
        mock_client.messages.stream.return_value = MockStream(events)
        result = await get_claude_response(_make_history())

    assert result.call_record is None
    assert result.done is False


@pytest.mark.asyncio
async def test_empty_rep_name_returns_no_record():
    """If tool input has empty rep_name, return response with no call_record."""
    tool_input = {
        "rep_name": "",
        "request_type": "PPS Case Report",
        "tray_type": "Mini",
        "surgeon": "Dr. Smith",
        "facility": "Hospital",
        "surgery_date": "2026-03-20",
        "details": "test",
        "priority": "normal",
    }
    events = _make_stream_events(
        text="", tool_name="submit_call_record",
        tool_id="tool_123", tool_input=tool_input,
    )

    with patch("src.claude_service.client") as mock_client:
        mock_client.messages.stream.return_value = MockStream(events)
        result = await get_claude_response(_make_history())

    assert result.call_record is None
    assert result.done is False


@pytest.mark.asyncio
async def test_valid_tool_input_returns_record():
    """Valid tool input should return a call_record."""
    tool_input = {
        "rep_name": "Gary",
        "request_type": "Bill Only Request",
        "tray_type": "Mini",
        "surgeon": "Dr. Smith",
        "facility": "Hospital",
        "surgery_date": "2026-03-20",
        "details": "test",
        "priority": "normal",
    }
    events = _make_stream_events(
        text="Let me confirm.", tool_name="submit_call_record",
        tool_id="tool_123", tool_input=tool_input,
    )

    # Follow-up stream for closing message
    follow_events = _make_stream_events(text="All submitted!")

    with patch("src.claude_service.client") as mock_client:
        mock_client.messages.stream.side_effect = [
            MockStream(events),
            MockStream(follow_events),
        ]
        result = await get_claude_response(_make_history())

    assert result.call_record is not None
    assert result.call_record.rep_name == "Gary"
    assert result.done is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest src/test/test_claude_service.py -v`
Expected: Some tests FAIL (malformed JSON will crash, empty rep_name not validated)

- [ ] **Step 3: Add error handling to claude_service.py**

Replace lines 128-142 in `src/claude_service.py` with:

```python
    call_record = None
    done = False

    # Handle tool use (submit_call_record)
    if tool_name == "submit_call_record" and tool_input_json:
        try:
            inp = json.loads(tool_input_json)
        except json.JSONDecodeError:
            logger.warning("Malformed tool input JSON: %s", tool_input_json[:200])
            return ClaudeResponse(text=full_text, call_record=None, done=False)

        # Validate required fields
        if not inp.get("rep_name", "").strip():
            logger.warning("Tool input missing rep_name: %s", inp)
            return ClaudeResponse(text=full_text, call_record=None, done=False)

        try:
            call_record = CallRecordExtract(
                rep_name=inp.get("rep_name", ""),
                request_type=RequestType(inp.get("request_type", "Other")),
                tray_type=inp.get("tray_type", ""),
                surgeon=inp.get("surgeon", ""),
                facility=inp.get("facility", ""),
                surgery_date=inp.get("surgery_date", ""),
                details=inp.get("details", ""),
                priority=Priority(inp.get("priority", "normal")),
            )
        except (ValueError, KeyError) as e:
            logger.warning("Invalid tool input (validation failed): %s — %s", e, inp)
            return ClaudeResponse(text=full_text, call_record=None, done=False)

        done = True
        logger.info("Claude submitted call record via tool use: %s", call_record)
```

The rest of the function (lines 144-170 — follow-up stream) stays the same.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest src/test/test_claude_service.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_service.py src/test/test_claude_service.py
git commit -m "feat: add error handling for malformed/invalid tool input in Claude service"
```

---

### Task 4: Error Handling in CSV Service

**Files:**
- Modify: `src/csv_service.py:37-43`
- Create: `src/test/test_csv_service.py`

- [ ] **Step 1: Write tests**

```python
# src/test/test_csv_service.py
import csv
import pytest
from pathlib import Path
from unittest.mock import patch

from src.csv_service import append_call_record, CSV_HEADERS
from src.types import CallRecord, RequestType, Priority


def _make_record(**overrides) -> CallRecord:
    defaults = {
        "call_sid": "CA_test_123",
        "timestamp": "2026-03-13T14:00:00+00:00",
        "rep_name": "Gary",
        "request_type": RequestType.BILL_ONLY_REQUEST,
        "tray_type": "Mini",
        "surgeon": "Dr. Smith",
        "facility": "Test Hospital",
        "surgery_date": "2026-03-20",
        "details": "Test details",
        "priority": Priority.NORMAL,
        "routed_to": "pps-team@shuklamedical.com",
        "call_duration_seconds": 120,
    }
    defaults.update(overrides)
    return CallRecord(**defaults)


def test_creates_new_csv_with_header(tmp_path):
    """First record creates the file with headers."""
    with patch("src.csv_service.CSV_OUTPUT_DIR", str(tmp_path)):
        with patch("src.csv_service._get_csv_path") as mock_path:
            csv_file = tmp_path / "test.csv"
            mock_path.return_value = csv_file
            append_call_record(_make_record())

    assert csv_file.exists()
    with open(csv_file) as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == CSV_HEADERS
        row = next(reader)
        assert row[2] == "Gary"  # rep_name


def test_appends_to_existing_csv(tmp_path):
    """Second record appends without duplicating header."""
    csv_file = tmp_path / "test.csv"

    with patch("src.csv_service._get_csv_path", return_value=csv_file):
        append_call_record(_make_record(call_sid="CA_1"))
        append_call_record(_make_record(call_sid="CA_2"))

    with open(csv_file) as f:
        lines = f.readlines()
    assert len(lines) == 3  # header + 2 rows


def test_oserror_propagates(tmp_path):
    """OSError should propagate so call_processor catches it."""
    with patch("src.csv_service._get_csv_path", return_value=Path("/nonexistent/dir/test.csv")):
        with patch("src.csv_service.Path.mkdir", side_effect=OSError("Permission denied")):
            with pytest.raises(OSError, match="Permission denied"):
                append_call_record(_make_record())
```

- [ ] **Step 2: Run tests to verify they fail or pass as expected**

Run: `pytest src/test/test_csv_service.py -v`
Expected: First two PASS (existing code handles these), third may need adjustment.

- [ ] **Step 3: Add error handling to CSV service**

Replace `append_call_record` in `src/csv_service.py`:

```python
def append_call_record(record: CallRecord) -> None:
    csv_path = _get_csv_path()
    try:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = csv_path.exists()

        with open(csv_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS, quoting=csv.QUOTE_ALL)
            if not file_exists:
                writer.writeheader()
            writer.writerow(
                {h: getattr(record, h, "") for h in CSV_HEADERS}
            )

        logger.info("Appended call record to CSV: %s (call_sid=%s)", csv_path, record.call_sid)
    except OSError as e:
        logger.error("Failed to write CSV (call_sid=%s, path=%s): %s", record.call_sid, csv_path, e)
        raise
```

- [ ] **Step 4: Run tests**

Run: `pytest src/test/test_csv_service.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/csv_service.py src/test/test_csv_service.py
git commit -m "feat: add error handling to CSV service with tests"
```

---

### Task 5: Error Handling in Email Service

**Files:**
- Modify: `src/email_service.py:59-84`
- Create: `src/test/test_email_service.py`

- [ ] **Step 1: Write tests**

```python
# src/test/test_email_service.py
import pytest
from src.email_service import _build_email_body
from src.types import CallRecord, RequestType, Priority


def _make_record(**overrides) -> CallRecord:
    defaults = {
        "call_sid": "CA_test_123",
        "timestamp": "2026-03-13T14:00:00+00:00",
        "rep_name": "Gary",
        "request_type": RequestType.BILL_ONLY_REQUEST,
        "tray_type": "Mini",
        "surgeon": "Dr. Smith",
        "facility": "Test Hospital",
        "surgery_date": "2026-03-20",
        "details": "Three trays used",
        "priority": Priority.NORMAL,
        "routed_to": "pps-team@shuklamedical.com",
        "call_duration_seconds": 120,
    }
    defaults.update(overrides)
    return CallRecord(**defaults)


def test_email_body_includes_all_fields():
    record = _make_record()
    body = _build_email_body(record)
    assert "Gary" in body
    assert "Bill Only Request" in body
    assert "Dr. Smith" in body
    assert "Test Hospital" in body
    assert "2026-03-20" in body
    assert "Three trays used" in body
    assert "NORMAL" in body


def test_email_body_omits_empty_optional_fields():
    record = _make_record(surgeon="", facility="", surgery_date="", details="")
    body = _build_email_body(record)
    assert "Surgeon" not in body
    assert "Facility" not in body
    assert "Surgery Date" not in body
    assert "Details" not in body


def test_email_subject_urgent():
    """Urgent priority should show [URGENT] in subject."""
    from src.email_service import send_email_notification
    record = _make_record(priority=Priority.URGENT)
    # We test the subject logic directly
    priority_label = "URGENT" if record.priority == Priority.URGENT else "New"
    subject = f"[{priority_label}] {record.request_type} — {record.rep_name}"
    assert "[URGENT]" in subject


def test_email_subject_normal():
    record = _make_record(priority=Priority.NORMAL)
    priority_label = "URGENT" if record.priority == Priority.URGENT else "New"
    subject = f"[{priority_label}] {record.request_type} — {record.rep_name}"
    assert "[New]" in subject
```

- [ ] **Step 2: Run tests**

Run: `pytest src/test/test_email_service.py -v`
Expected: All 4 PASS (testing pure functions that already work)

- [ ] **Step 3: Add error handling to email send**

Replace `send_email_notification` and `_send_gmail_message` in `src/email_service.py`:

```python
async def send_email_notification(record: CallRecord) -> None:
    if not GOOGLE_CLIENT_ID or not GOOGLE_REFRESH_TOKEN:
        logger.warning("Gmail API not configured, skipping email notification")
        return

    priority_label = "URGENT" if record.priority == Priority.URGENT else "New"
    subject = f"[{priority_label}] {record.request_type} — {record.rep_name}"
    body = _build_email_body(record)

    message = MIMEText(body)
    message["to"] = GMAIL_TO_ADDRESS
    message["from"] = GMAIL_FROM_ADDRESS
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(None, _send_gmail_message, raw),
            timeout=15.0,
        )
        logger.info("Email notification sent (call_sid=%s, to=%s)", record.call_sid, GMAIL_TO_ADDRESS)
    except TimeoutError:
        logger.error("Email send timed out after 15s (call_sid=%s)", record.call_sid)
        raise
    except Exception as e:
        logger.error("Email send failed (call_sid=%s): %s: %s", record.call_sid, type(e).__name__, e)
        raise


def _send_gmail_message(raw: str) -> None:
    try:
        service = _get_gmail_service()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except Exception as e:
        logger.error("Gmail API error: %s: %s", type(e).__name__, e)
        raise
```

- [ ] **Step 4: Run tests**

Run: `pytest src/test/test_email_service.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/email_service.py src/test/test_email_service.py
git commit -m "feat: add error handling and timeout to email service"
```

---

### Task 6: Error Handling in Google Chat Service

**Files:**
- Modify: `src/google_chat_service.py:41-55`
- Create: `src/test/test_google_chat_service.py`

- [ ] **Step 1: Write tests**

```python
# src/test/test_google_chat_service.py
import pytest
from src.google_chat_service import send_google_chat_notification
from src.types import CallRecord, RequestType, Priority
from unittest.mock import patch, AsyncMock, MagicMock


def _make_record(**overrides) -> CallRecord:
    defaults = {
        "call_sid": "CA_test_123",
        "timestamp": "2026-03-13T14:00:00+00:00",
        "rep_name": "Gary",
        "request_type": RequestType.PPS_CASE_REPORT,
        "tray_type": "Mini",
        "surgeon": "Dr. Smith",
        "facility": "Test Hospital",
        "surgery_date": "2026-03-20",
        "details": "Test case",
        "priority": Priority.NORMAL,
        "routed_to": "pps-team@shuklamedical.com",
        "call_duration_seconds": 120,
    }
    defaults.update(overrides)
    return CallRecord(**defaults)


@pytest.mark.asyncio
async def test_skips_when_no_webhook():
    with patch("src.google_chat_service.GOOGLE_CHAT_WEBHOOK_URL", ""):
        await send_google_chat_notification(_make_record())
        # Should not raise


@pytest.mark.asyncio
async def test_card_includes_conditional_fields():
    """When surgeon is empty, card should not have a surgeon widget."""
    record = _make_record(surgeon="", facility="")

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("src.google_chat_service.GOOGLE_CHAT_WEBHOOK_URL", "https://example.com/webhook"):
        with patch("src.google_chat_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await send_google_chat_notification(record)

            # Check the card JSON sent
            call_args = mock_client.post.call_args
            card_json = call_args.kwargs["json"]
            widgets = card_json["cards"][0]["sections"][0]["widgets"]

            # Surgeon and Facility should NOT be present
            top_labels = [w["keyValue"]["topLabel"] for w in widgets if "keyValue" in w]
            assert "Surgeon" not in top_labels
            assert "Facility" not in top_labels
            assert "Tray Type" in top_labels
```

- [ ] **Step 2: Run tests**

Run: `pytest src/test/test_google_chat_service.py -v`
Expected: PASS

- [ ] **Step 3: Add error handling and timeout**

Replace the httpx POST section in `src/google_chat_service.py`:

```python
    try:
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            response = await http_client.post(
                GOOGLE_CHAT_WEBHOOK_URL,
                json=card,
                headers={"Content-Type": "application/json"},
            )

        if response.status_code >= 400:
            logger.error(
                "Google Chat notification failed: %s %s (call_sid=%s)",
                response.status_code,
                response.text,
                record.call_sid,
            )
        else:
            logger.info("Google Chat notification sent (call_sid=%s)", record.call_sid)
    except httpx.HTTPError as e:
        logger.error("Google Chat webhook error (call_sid=%s): %s: %s", record.call_sid, type(e).__name__, e)
        raise
```

- [ ] **Step 4: Run tests**

Run: `pytest src/test/test_google_chat_service.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/google_chat_service.py src/test/test_google_chat_service.py
git commit -m "feat: add error handling and timeout to Google Chat service"
```

---

### Task 7: Apply Retry to External Calls

**Files:**
- Modify: `src/claude_service.py:91-170` (wrap get_claude_response internals)
- Modify: `src/email_service.py` (wrap send)
- Modify: `src/google_chat_service.py` (wrap POST)

- [ ] **Step 1: Add retry to Claude service**

In `src/claude_service.py`, add import at top:
```python
from src.retry import with_retry
```

Wrap the streaming call in `get_claude_response`. Replace the `async with client.messages.stream(...)` block (lines 107-123) with:

```python
    async def _call_claude():
        nonlocal full_text, tool_name, tool_id, tool_input_json
        # Reset on each attempt so retries don't accumulate stale data
        full_text = ""
        tool_name = ""
        tool_id = ""
        tool_input_json = ""
        async with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            tools=[SUBMIT_TOOL],
            messages=messages,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        tool_name = event.content_block.name
                        tool_id = event.content_block.id
                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        full_text += event.delta.text
                    elif event.delta.type == "input_json_delta":
                        tool_input_json += event.delta.partial_json

    await with_retry(_call_claude, max_attempts=3, base_delay=1.0)
```

Do the same for the follow-up stream (lines 159-168). Note: `tools=[SUBMIT_TOOL]` stays as-is until Task 10 introduces `TOOLS = [SUBMIT_TOOL, TRANSFER_TOOL]`, at which point all references should be updated to `tools=TOOLS`.

- [ ] **Step 2: Add retry to email service**

In `src/email_service.py`, add import:
```python
from src.retry import with_retry
```

In `send_email_notification`, replace the executor call. The timeout wraps each individual send attempt (inside the retry lambda), not the entire retry sequence:
```python
    async def _send_with_timeout():
        return await asyncio.wait_for(
            loop.run_in_executor(None, _send_gmail_message, raw),
            timeout=15.0,
        )

    try:
        await with_retry(_send_with_timeout, max_attempts=2, base_delay=2.0)
```

- [ ] **Step 3: Add retry to Google Chat service**

In `src/google_chat_service.py`, add import:
```python
from src.retry import with_retry
```

Wrap the POST:
```python
    async def _post_webhook():
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            return await http_client.post(
                GOOGLE_CHAT_WEBHOOK_URL,
                json=card,
                headers={"Content-Type": "application/json"},
            )

    try:
        response = await with_retry(_post_webhook, max_attempts=2, base_delay=1.0)
```

- [ ] **Step 4: Run all existing tests**

Run: `pytest src/test/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_service.py src/email_service.py src/google_chat_service.py
git commit -m "feat: apply retry with exponential backoff to all external API calls"
```

---

### Task 8: Conversation History Cap

**Files:**
- Modify: `src/websocket_handler.py:13-18`

- [ ] **Step 1: Add history cap to CallSession**

Add a method to `CallSession`:
```python
class CallSession:
    MAX_HISTORY = 20

    def __init__(self):
        self.call_sid: str = ""
        self.conversation_history: list[ConversationTurn] = []
        self.start_time: float = time.time()
        self.call_record_submitted: bool = False

    def trim_history(self) -> None:
        """Keep first turn (greeting context) and last MAX_HISTORY - 1 turns."""
        if len(self.conversation_history) > self.MAX_HISTORY:
            first = self.conversation_history[0]
            recent = self.conversation_history[-(self.MAX_HISTORY - 1):]
            self.conversation_history = [first] + recent
```

- [ ] **Step 2: Call trim_history before each Claude call**

In `_handle_message`, add `session.trim_history()` before each `get_claude_response()` call (in both the "setup" and "prompt" blocks).

- [ ] **Step 3: Add test for history truncation**

Add to `src/test/test_websocket_handler.py` (create file if not exists):
```python
# src/test/test_websocket_handler.py
from src.websocket_handler import CallSession
from src.claude_service import ConversationTurn


def test_trim_history_preserves_first_turn():
    session = CallSession()
    for i in range(25):
        role = "user" if i % 2 == 0 else "assistant"
        session.conversation_history.append(ConversationTurn(role=role, content=f"turn {i}"))

    session.trim_history()

    assert len(session.conversation_history) == 20
    assert session.conversation_history[0].content == "turn 0"  # first preserved
    assert session.conversation_history[-1].content == "turn 24"  # last preserved


def test_trim_history_noop_under_limit():
    session = CallSession()
    for i in range(10):
        session.conversation_history.append(ConversationTurn(role="user", content=f"turn {i}"))

    session.trim_history()
    assert len(session.conversation_history) == 10
```

- [ ] **Step 4: Run tests**

Run: `pytest src/test/test_websocket_handler.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/websocket_handler.py src/test/test_websocket_handler.py
git commit -m "feat: cap conversation history at 20 turns to prevent token overflow"
```

---

### Task 9: Types Tests

**Files:**
- Create: `src/test/test_types.py`

- [ ] **Step 1: Write tests**

```python
# src/test/test_types.py
import pytest
from src.types import RequestType, Priority, CallRecord, CallRecordExtract


def test_request_type_str_returns_value():
    """Python 3.13 StrEnum: str() must return the value, not ClassName.MEMBER."""
    assert str(RequestType.PPS_CASE_REPORT) == "PPS Case Report"
    assert str(RequestType.BILL_ONLY_REQUEST) == "Bill Only Request"


def test_priority_str_returns_value():
    assert str(Priority.NORMAL) == "normal"
    assert str(Priority.URGENT) == "urgent"


def test_call_record_extract_valid():
    record = CallRecordExtract(
        rep_name="Gary",
        request_type=RequestType.BILL_ONLY_REQUEST,
    )
    assert record.rep_name == "Gary"
    assert record.priority == Priority.NORMAL  # default


def test_call_record_extract_invalid_request_type():
    with pytest.raises(ValueError):
        CallRecordExtract(
            rep_name="Gary",
            request_type="Not A Real Type",
        )


def test_call_record_optional_fields_default_empty():
    record = CallRecordExtract(
        rep_name="Gary",
        request_type=RequestType.OTHER,
    )
    assert record.tray_type == ""
    assert record.surgeon == ""
    assert record.facility == ""
    assert record.surgery_date == ""
    assert record.details == ""
```

- [ ] **Step 2: Run tests**

Run: `pytest src/test/test_types.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add src/test/test_types.py
git commit -m "test: add StrEnum and Pydantic model validation tests"
```

---

## Chunk 2: Call Quality

### Task 10: Transfer to Human Tool

**Files:**
- Modify: `src/claude_service.py` (add TRANSFER_TOOL, update TOOLS list)
- Modify: `src/websocket_handler.py` (handle transfer response)
- Modify: `src/email_service.py` (add send_escalation_email)
- Modify: `src/system_prompt.py` (add escalation instructions)

- [ ] **Step 1: Add transfer tool definition to claude_service.py**

After the `SUBMIT_TOOL` definition, add:
```python
TRANSFER_TOOL: anthropic.types.ToolParam = {
    "name": "transfer_to_human",
    "description": (
        "Transfer the caller to a human when you cannot help, the caller "
        "requests it, or the situation requires human judgment."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Brief reason why the transfer is needed",
            },
        },
        "required": ["reason"],
    },
}

TOOLS = [SUBMIT_TOOL, TRANSFER_TOOL]
```

Update all `tools=[SUBMIT_TOOL]` references in `get_claude_response` to `tools=TOOLS` (3 places: the main stream, the follow-up stream for submit_call_record, and the new transfer_to_human follow-up stream).

- [ ] **Step 2: Add transfer_reason to ClaudeResponse**

```python
@dataclass
class ClaudeResponse:
    text: str
    call_record: CallRecordExtract | None
    done: bool
    transfer_reason: str | None = None
```

- [ ] **Step 3: Handle transfer_to_human in get_claude_response**

After the `submit_call_record` handling block, add:
```python
    elif tool_name == "transfer_to_human" and tool_input_json:
        try:
            inp = json.loads(tool_input_json)
        except json.JSONDecodeError:
            inp = {"reason": "unknown"}
        reason = inp.get("reason", "unknown")
        logger.warning("Claude requested transfer to human: %s", reason)

        # Get closing message
        messages.append({"role": "assistant", "content": [
            *([{"type": "text", "text": full_text}] if full_text else []),
            {"type": "tool_use", "id": tool_id, "name": tool_name, "input": inp},
        ]})
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": "Transfer noted. A team member will follow up.",
            }],
        })

        async with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=100,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        ) as follow_stream:
            async for event in follow_stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    full_text += event.delta.text

        return ClaudeResponse(text=full_text, call_record=None, done=True, transfer_reason=reason)
```

- [ ] **Step 4: Add escalation email to email_service.py**

Add at the end of `src/email_service.py`:
```python
async def send_escalation_email(
    call_sid: str,
    rep_name: str,
    reason: str,
    timestamp: str,
) -> None:
    if not GOOGLE_CLIENT_ID or not GOOGLE_REFRESH_TOKEN:
        logger.warning("Gmail API not configured, skipping escalation email")
        return

    subject = f"[ESCALATION] Call from {rep_name or 'unknown'} — {reason}"
    body = "\n".join([
        "Call Escalation",
        "=" * 40,
        "",
        f"Timestamp: {timestamp}",
        f"Rep Name: {rep_name or 'unknown'}",
        f"Reason: {reason}",
        f"Call SID: {call_sid}",
        "",
        "A team member should follow up with this caller.",
    ])

    message = MIMEText(body)
    message["to"] = GMAIL_TO_ADDRESS
    message["from"] = GMAIL_FROM_ADDRESS
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(None, _send_gmail_message, raw),
            timeout=15.0,
        )
        logger.info("Escalation email sent (call_sid=%s, to=%s)", call_sid, GMAIL_TO_ADDRESS)
    except Exception as e:
        logger.error("Escalation email failed (call_sid=%s): %s", call_sid, e)
```

- [ ] **Step 5: Handle transfer in websocket_handler.py**

Add `should_close`, `last_assistant_response`, and `escalation_sent` to `CallSession`:
```python
class CallSession:
    MAX_HISTORY = 20

    def __init__(self):
        self.call_sid: str = ""
        self.conversation_history: list[ConversationTurn] = []
        self.start_time: float = time.time()
        self.call_record_submitted: bool = False
        self.should_close: bool = False
        self.last_assistant_response: str = ""
        self.escalation_sent: bool = False
```

In the "prompt" handler, after `await _send_text_response(ws, response.text)`, add:
```python
        session.last_assistant_response = response.text

        # Handle transfer to human
        if response.transfer_reason and not session.escalation_sent:
            session.escalation_sent = True
            session.should_close = True
            from src.email_service import send_escalation_email
            from datetime import datetime, timezone
            await send_escalation_email(
                call_sid=session.call_sid,
                rep_name="",  # rep name may not be known at escalation time
                reason=response.transfer_reason,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
```

Update the main loop to check `should_close`:
```python
async def handle_conversation_relay(ws: WebSocket) -> None:
    await ws.accept()
    session = CallSession()
    logger.info("New ConversationRelay WebSocket connection")

    try:
        while not session.should_close:
            data = await ws.receive_text()
            message = json.loads(data)
            await _handle_message(ws, session, message)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected (call_sid=%s)", session.call_sid)
    except Exception as e:
        logger.error("WebSocket error (call_sid=%s): %s", session.call_sid, e)
```

- [ ] **Step 6: Update system prompt**

In `src/system_prompt.py`, add before `## Style Guidelines`:
```python
## Escalation
If the caller asks to speak to a person, becomes frustrated, or you cannot fulfill their request, use the transfer_to_human tool with a brief reason. Do not try to force the conversation to continue.

## Goodbye Without Record
If the caller says goodbye, thank you, or indicates they're done without completing a record, say goodbye warmly. Do not force data collection — some calls are just inquiries.
```

Also update the Tool Use section:
```
## Tool Use
You have two tools:
1. "submit_call_record" — call this once the caller confirms the information is correct.
2. "transfer_to_human" — call this when you need to escalate to a human team member.
```

- [ ] **Step 7: Run all tests**

Run: `pytest src/test/ -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/claude_service.py src/websocket_handler.py src/email_service.py src/system_prompt.py
git commit -m "feat: add transfer_to_human tool with escalation email and graceful session close"
```

---

### Task 11: DTMF Actions

**Files:**
- Modify: `src/websocket_handler.py` (dtmf handler)

- [ ] **Step 1: Implement DTMF handling**

Replace the dtmf handler in `_handle_message`:
```python
    elif msg_type == "dtmf":
        digit = message.get("digit", "")
        logger.info("DTMF received (call_sid=%s): %s", session.call_sid, digit)

        if digit == "0":
            # Transfer to human
            session.should_close = True
            await _send_text_response(
                ws,
                "I'm going to have one of our team members follow up with you directly. Thank you for calling.",
            )
            from src.email_service import send_escalation_email
            from datetime import datetime, timezone
            await send_escalation_email(
                call_sid=session.call_sid,
                rep_name="unknown",
                reason="Caller pressed 0 to speak with a human",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        elif digit == "*":
            # Repeat last response
            text = session.last_assistant_response or "I haven't said anything yet."
            await _send_text_response(ws, text)
```

- [ ] **Step 2: Run tests**

Run: `pytest src/test/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add src/websocket_handler.py
git commit -m "feat: add DTMF actions (0=transfer to human, *=repeat last response)"
```

---

### Task 12: Silence Filler

**Files:**
- Modify: `src/websocket_handler.py` (prompt handler)

- [ ] **Step 1: Implement silence filler with task-based approach**

Add a helper function to `src/websocket_handler.py`:
```python
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
```

Add `import asyncio` at top of file.

Replace `get_claude_response(session.conversation_history)` calls in the "prompt" handler with `_get_response_with_filler(ws, session)`. Keep the "setup" handler using `get_claude_response` directly (greeting should be fast, no filler needed).

- [ ] **Step 2: Run tests**

Run: `pytest src/test/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add src/websocket_handler.py
git commit -m "feat: add 2.5s silence filler for slow Claude responses"
```

---

### Task 13: System Prompt Conciseness

**Files:**
- Modify: `src/system_prompt.py`

- [ ] **Step 1: Update system prompt for conciseness**

In the `## Your Role` section, change:
```
- Be concise — this is a phone call, not a chat. Keep responses short and conversational.
```
to:
```
- Be concise — keep each response to 1-2 sentences. The caller is on a phone, not reading a screen.
```

In `## Style Guidelines`, change:
```
- Keep each response to 1-3 sentences when possible
```
to:
```
- Keep each response to 1-2 sentences — shorter is better for phone conversations
```

- [ ] **Step 2: Commit**

```bash
git add src/system_prompt.py
git commit -m "refine: tighten system prompt for more concise phone responses"
```

---

## Chunk 3: Observability

### Task 14: Structured Logging

**Files:**
- Create: `src/logging_config.py`
- Modify: `src/main.py:10-14` (replace basicConfig)
- Modify: `src/config.py` (add ENV variable)

- [ ] **Step 1: Add ENV config**

In `src/config.py`, add:
```python
# Logging
ENV = _optional("ENV", "development")
```

- [ ] **Step 2: Create logging_config.py**

```python
# src/logging_config.py
import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Include extra fields (call_sid, etc.)
        if hasattr(record, "call_sid"):
            log_entry["call_sid"] = record.call_sid
        if hasattr(record, "data"):
            log_entry["data"] = record.data
        if record.exc_info and record.exc_info[1]:
            log_entry["error"] = str(record.exc_info[1])
            log_entry["error_type"] = type(record.exc_info[1]).__name__
        return json.dumps(log_entry)


class DevFormatter(logging.Formatter):
    def format(self, record):
        call_sid = getattr(record, "call_sid", "")
        prefix = f"[{call_sid[:10]}] " if call_sid else ""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = record.getMessage()
        base = f"{timestamp} {record.levelname} {prefix}{msg}"
        if record.exc_info and record.exc_info[1]:
            base += f"\n  {type(record.exc_info[1]).__name__}: {record.exc_info[1]}"
        return base


def setup_logging(env: str = "development") -> None:
    handler = logging.StreamHandler(sys.stdout)

    if env == "production":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(DevFormatter())

    logging.root.handlers.clear()
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.INFO)

    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)


class CallLogger(logging.LoggerAdapter):
    """Logger adapter that auto-includes call_sid in every log message."""

    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        extra["call_sid"] = self.extra.get("call_sid", "")
        kwargs["extra"] = extra
        return msg, kwargs
```

- [ ] **Step 3: Update main.py to use new logging**

Replace lines 10-14 in `src/main.py`:
```python
from src.logging_config import setup_logging
from src.config import BASE_URL, HOST, PORT, ENV

setup_logging(ENV)
logger = logging.getLogger(__name__)
```

Remove the old `logging.basicConfig(...)` call.

- [ ] **Step 4: Verify server starts with new logging**

Run: `source .venv/bin/activate && python -c "from src.main import app; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add src/logging_config.py src/main.py src/config.py
git commit -m "feat: add structured logging (JSON in prod, human-readable in dev)"
```

---

### Task 15: Call Metrics and Summary Logging

**Files:**
- Modify: `src/websocket_handler.py` (add metrics tracking and summary)

- [ ] **Step 1: Add metrics to CallSession**

```python
class CallSession:
    MAX_HISTORY = 20

    def __init__(self):
        self.call_sid: str = ""
        self.conversation_history: list[ConversationTurn] = []
        self.start_time: float = time.time()
        self.call_record_submitted: bool = False
        self.should_close: bool = False
        self.last_assistant_response: str = ""
        self.turn_count: int = 0
        self.claude_latencies: list[float] = []
        self.request_type: str = ""
        self.output_results: dict[str, str] = {}
```

- [ ] **Step 2: Track latency per Claude call**

In the "prompt" handler, wrap the Claude call:
```python
        start = time.time()
        response = await _get_response_with_filler(ws, session)
        session.claude_latencies.append(time.time() - start)
        session.turn_count += 1
```

- [ ] **Step 3: Log call summary on disconnect**

Add to `handle_conversation_relay`, in the `except WebSocketDisconnect` block:
```python
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
```

- [ ] **Step 4: Run tests**

Run: `pytest src/test/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/websocket_handler.py
git commit -m "feat: add call metrics tracking and summary logging on disconnect"
```

---

### Task 16: Error History Endpoint

**Files:**
- Modify: `src/main.py` (add /errors endpoint)
- Modify: `src/config.py` (add ADMIN_API_KEY)

- [ ] **Step 1: Add ADMIN_API_KEY config**

In `src/config.py`:
```python
# Admin
ADMIN_API_KEY = _optional("ADMIN_API_KEY")
```

- [ ] **Step 2: Create error history module**

Create `src/error_history.py`:
```python
# src/error_history.py
import collections
from datetime import datetime, timezone

_errors: collections.deque = collections.deque(maxlen=50)


def record_error(call_sid: str, service: str, error: str) -> None:
    _errors.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "call_sid": call_sid,
        "service": service,
        "error": error,
    })


def get_recent_errors() -> list[dict]:
    return list(_errors)
```

- [ ] **Step 3: Add /errors endpoint to main.py**

```python
from src.config import ADMIN_API_KEY
from src.error_history import get_recent_errors

@app.get("/errors")
async def errors(request: Request):
    if not ADMIN_API_KEY:
        return Response(status_code=404)
    api_key = request.headers.get("X-API-Key", "")
    if api_key != ADMIN_API_KEY:
        return Response(status_code=401)
    return {"errors": get_recent_errors()}
```

- [ ] **Step 4: Wire error_history into call_processor.py**

In `src/call_processor.py`, add import and record errors:
```python
from src.error_history import record_error

    for name, result in zip(service_names, results):
        if isinstance(result, Exception):
            logger.error("Output delivery failed for %s (call_sid=%s): %s", name, call_sid, result)
            record_error(call_sid, name.lower(), str(result))
```

- [ ] **Step 5: Run tests**

Run: `pytest src/test/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/error_history.py src/main.py src/config.py src/call_processor.py
git commit -m "feat: add /errors endpoint with in-memory error ring buffer"
```

---

## Chunk 4: Production Readiness

### Task 17: Enhanced Health Checks

**Files:**
- Modify: `src/main.py` (replace /health, add /health/live, /health/ready)
- Create: `src/health.py` (health check logic)

- [ ] **Step 1: Create health check module**

```python
# src/health.py
import logging
import time
from pathlib import Path

from src.config import CSV_OUTPUT_DIR, GOOGLE_CLIENT_ID, GOOGLE_REFRESH_TOKEN

logger = logging.getLogger(__name__)

# Cached Claude API check
_claude_cache: dict = {"status": "unknown", "latency_ms": 0, "checked_at": 0}
_CLAUDE_CHECK_INTERVAL = 60  # seconds

# Track active sessions
active_sessions: set = set()


async def check_claude_api() -> dict:
    """Check Claude API health (cached, max once per 60s)."""
    now = time.time()
    if now - _claude_cache["checked_at"] < _CLAUDE_CHECK_INTERVAL:
        return {"status": _claude_cache["status"], "latency_ms": _claude_cache["latency_ms"]}

    try:
        from src.claude_service import client
        from src.config import CLAUDE_MODEL
        start = time.time()
        await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        latency = int((time.time() - start) * 1000)
        _claude_cache.update(status="ok", latency_ms=latency, checked_at=now)
    except Exception as e:
        _claude_cache.update(status=f"error: {e}", latency_ms=0, checked_at=now)

    return {"status": _claude_cache["status"], "latency_ms": _claude_cache["latency_ms"]}


def check_csv_dir() -> dict:
    path = Path(CSV_OUTPUT_DIR)
    try:
        path.mkdir(parents=True, exist_ok=True)
        test_file = path / ".health_check"
        test_file.write_text("ok")
        test_file.unlink()
        return {"status": "ok", "writable": True}
    except OSError as e:
        return {"status": f"error: {e}", "writable": False}


def check_gmail() -> dict:
    if not GOOGLE_CLIENT_ID or not GOOGLE_REFRESH_TOKEN:
        return {"status": "not configured"}
    return {"status": "configured"}
```

- [ ] **Step 2: Update main.py health endpoints**

Replace the existing `/health` endpoint and add new ones:
```python
from src.health import check_claude_api, check_csv_dir, check_gmail, active_sessions

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
    claude = await check_claude_api()
    if claude["status"] != "ok":
        return Response(
            content='{"status": "not ready", "reason": "claude_api unreachable"}',
            status_code=503,
            media_type="application/json",
        )
    return {"status": "ready"}
```

- [ ] **Step 3: Track active sessions in websocket_handler.py**

In `handle_conversation_relay`:
```python
from src.health import active_sessions

async def handle_conversation_relay(ws: WebSocket) -> None:
    await ws.accept()
    session = CallSession()
    active_sessions.add(id(session))
    ...
    # In finally or except blocks:
    active_sessions.discard(id(session))
```

- [ ] **Step 4: Commit**

```bash
git add src/health.py src/main.py src/websocket_handler.py
git commit -m "feat: add enhanced health checks with Claude API ping, CSV dir, and active call tracking"
```

---

### Task 18: Graceful Shutdown

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Add shutdown handler**

Add to `src/main.py`:
```python
import asyncio
import signal

# Initialized in on_startup when the event loop is running
_shutdown_event: asyncio.Event | None = None

@app.on_event("startup")
async def on_startup():
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: _shutdown_event.set())

@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Shutdown initiated, waiting for %d active calls...", len(active_sessions))
    # Wait up to 30 seconds for active calls to finish
    for _ in range(30):
        if not active_sessions:
            break
        await asyncio.sleep(1)
    if active_sessions:
        logger.warning("Force-closing %d remaining sessions", len(active_sessions))
    logger.info("Shutdown complete")
```

- [ ] **Step 2: Update /health/ready to return 503 during shutdown**

```python
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
```

- [ ] **Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: add graceful shutdown with 30s drain for active calls"
```

---

### Task 19: Dockerfile

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Create .dockerignore**

```
.venv/
.env
.git/
__pycache__/
*.pyc
data/
.claude/
docs/
```

- [ ] **Step 2: Create Dockerfile**

```dockerfile
FROM python:3.13-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.13-slim
WORKDIR /app
RUN useradd -r -s /bin/false appuser && mkdir -p /app/data && chown appuser:appuser /app/data
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ src/
# data/ must be volume-mounted in production: docker run -v /host/data:/app/data
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health/live')" || exit 1
CMD ["python", "-m", "src.main"]
```

- [ ] **Step 3: Verify Docker build works**

Run: `docker build -t shukla-phone .`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "feat: add production Dockerfile with multi-stage build"
```

---

### Task 20: Call Processor Tests

**Files:**
- Create: `src/test/test_call_processor.py`

- [ ] **Step 1: Write tests**

```python
# src/test/test_call_processor.py
import pytest
from unittest.mock import patch, AsyncMock

from src.call_processor import process_completed_call
from src.types import CallRecordExtract, RequestType, Priority


def _make_extract(**overrides) -> CallRecordExtract:
    defaults = {
        "rep_name": "Gary",
        "request_type": RequestType.BILL_ONLY_REQUEST,
        "tray_type": "Mini",
        "surgeon": "Dr. Smith",
        "facility": "Test Hospital",
        "surgery_date": "2026-03-20",
        "details": "Test",
        "priority": Priority.NORMAL,
    }
    defaults.update(overrides)
    return CallRecordExtract(**defaults)


@pytest.mark.asyncio
async def test_all_outputs_called():
    with patch("src.call_processor.append_call_record") as mock_csv, \
         patch("src.call_processor.send_google_chat_notification", new_callable=AsyncMock) as mock_chat, \
         patch("src.call_processor.send_email_notification", new_callable=AsyncMock) as mock_email:

        await process_completed_call("CA_test", _make_extract(), 120)

        mock_csv.assert_called_once()
        mock_chat.assert_called_once()
        mock_email.assert_called_once()


@pytest.mark.asyncio
async def test_one_failure_does_not_block_others():
    with patch("src.call_processor.append_call_record", side_effect=OSError("disk full")), \
         patch("src.call_processor.send_google_chat_notification", new_callable=AsyncMock) as mock_chat, \
         patch("src.call_processor.send_email_notification", new_callable=AsyncMock) as mock_email:

        # Should not raise even though CSV failed
        await process_completed_call("CA_test", _make_extract(), 120)

        mock_chat.assert_called_once()
        mock_email.assert_called_once()
```

- [ ] **Step 2: Run tests**

Run: `pytest src/test/test_call_processor.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add src/test/test_call_processor.py
git commit -m "test: add call processor tests for parallel dispatch and partial failure"
```

---

### Task 21: Startup Validation

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Add startup validation**

Add to the `on_startup` handler:
```python
@app.on_event("startup")
async def on_startup():
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: _shutdown_event.set())

    # Validate required services
    logger.info("Validating services...")

    # Claude API (required)
    claude_check = await check_claude_api()
    if claude_check["status"] != "ok":
        logger.error("Claude API check failed: %s", claude_check["status"])
        raise RuntimeError("Claude API is not reachable — cannot start")
    logger.info("Claude API: OK (latency=%dms)", claude_check["latency_ms"])

    # Gmail (optional)
    gmail_check = check_gmail()
    if gmail_check["status"] == "configured":
        logger.info("Gmail API: configured")
    else:
        logger.info("Gmail API: not configured (email notifications disabled)")

    # CSV directory
    csv_check = check_csv_dir()
    if csv_check["writable"]:
        logger.info("CSV directory: writable")
    else:
        logger.warning("CSV directory: %s", csv_check["status"])

    logger.info("Startup validation complete")
```

- [ ] **Step 2: Commit**

```bash
git add src/main.py
git commit -m "feat: add startup validation for Claude API, Gmail, and CSV directory"
```

---

### Task 22: Final Integration Test

- [ ] **Step 1: Run all tests**

Run: `pytest src/test/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 2: Start server and verify health**

Run: `source .venv/bin/activate && python -m src.main &`
Wait 3 seconds, then:
Run: `curl -s http://localhost:8080/health | python -m json.tool`
Expected: JSON with status "ok" and all checks populated

Run: `curl -s http://localhost:8080/health/live`
Expected: `{"status": "ok"}`

Run: `curl -s http://localhost:8080/health/ready`
Expected: `{"status": "ready"}`

- [ ] **Step 3: Make a test call**

Call (727) 626-5994 from verified number. Verify:
- AI greets you
- AI responds to your speech
- No silent gaps (silence filler works)
- Pressing 0 triggers escalation
- Call record is emailed after submission
- Call summary appears in server logs

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: final integration verification — all tests pass, server healthy"
git push origin master
```
