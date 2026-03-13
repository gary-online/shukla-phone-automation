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
