import logging
import time
from pathlib import Path

from src.config import CSV_OUTPUT_DIR, GOOGLE_CLIENT_ID, GOOGLE_REFRESH_TOKEN

logger = logging.getLogger(__name__)

# Cached Claude API check
_claude_cache: dict = {"status": "unknown", "latency_ms": 0, "checked_at": 0}
_CLAUDE_CHECK_INTERVAL = 60

# Track active sessions
active_sessions: set = set()


async def check_claude_api() -> dict:
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
