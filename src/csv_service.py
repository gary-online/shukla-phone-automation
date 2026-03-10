import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.config import CSV_OUTPUT_DIR
from src.types import CallRecord

logger = logging.getLogger(__name__)

CSV_HEADERS = [
    "call_sid",
    "timestamp",
    "rep_name",
    "request_type",
    "tray_type",
    "surgeon",
    "facility",
    "surgery_date",
    "details",
    "priority",
    "routed_to",
    "call_duration_seconds",
]


def _get_csv_path() -> Path:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m")
    return Path(CSV_OUTPUT_DIR) / f"call-records-{date_str}.csv"


def append_call_record(record: CallRecord) -> None:
    csv_path = _get_csv_path()
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
