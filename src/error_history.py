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
