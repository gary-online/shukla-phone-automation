import csv
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from src.config import CSV_OUTPUT_DIR
from src.types import CallRecord

logger = logging.getLogger(__name__)

_csv_lock = threading.Lock()

CSV_HEADERS = [
    "call_sid",
    "timestamp",
    "rep_name",
    "request_type",
    "tray_type",
    "tray_details",
    "surgeon",
    "facility",
    "facility_address",
    "customer_id",
    "surgery_date",
    "details",
    "priority",
    "routed_to",
    "call_duration_seconds",
    "case_number",
    "sender_info",
    "recipient_info",
    "shipping_priority",
    "shipment_weight",
    "return_label_needed",
]


def _get_csv_path() -> Path:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m")
    return Path(CSV_OUTPUT_DIR) / f"call-records-{date_str}.csv"


def append_call_record(record: CallRecord) -> None:
    csv_path = _get_csv_path()
    try:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with _csv_lock:
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
        logger.error("Failed to write CSV (call_sid=%s): %s", record.call_sid, e)
        raise
