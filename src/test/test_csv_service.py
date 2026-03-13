import csv
from pathlib import Path
from unittest.mock import patch

import pytest

from src.csv_service import CSV_HEADERS, append_call_record
from src.test.conftest import make_record


def test_creates_new_csv_with_header(tmp_path):
    csv_path = tmp_path / "call-records-2026-03.csv"
    with patch("src.csv_service._get_csv_path", return_value=csv_path):
        append_call_record(make_record())

    assert csv_path.exists()
    with open(csv_path) as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == CSV_HEADERS
        row = next(reader)
        assert row[0] == "CA123"
        assert row[2] == "John Smith"


def test_appends_to_existing(tmp_path):
    csv_path = tmp_path / "call-records-2026-03.csv"
    with patch("src.csv_service._get_csv_path", return_value=csv_path):
        append_call_record(make_record(call_sid="CA001"))
        append_call_record(make_record(call_sid="CA002"))

    with open(csv_path) as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == CSV_HEADERS
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0][0] == "CA001"
        assert rows[1][0] == "CA002"


def test_oserror_propagates(tmp_path):
    bad_path = Path("/proc/nonexistent/call-records.csv")
    with patch("src.csv_service._get_csv_path", return_value=bad_path):
        with pytest.raises(OSError):
            append_call_record(make_record())


def test_new_fields_in_csv(tmp_path):
    csv_path = tmp_path / "call-records-2026-03.csv"
    record = make_record(
        facility_address="123 Main St, Dallas TX 75201",
        customer_id="CUST-456",
        tray_details="Mini — $500 — consignment",
        case_number="REF-789",
        sender_info="John, Acme, 123 Main St",
        recipient_info="Jane, Hospital, 456 Oak Ave",
        shipping_priority="overnight",
        shipment_weight="10 lbs",
        return_label_needed="yes",
    )
    with patch("src.csv_service._get_csv_path", return_value=csv_path):
        append_call_record(record)

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        row = next(reader)
        assert row["facility_address"] == "123 Main St, Dallas TX 75201"
        assert row["customer_id"] == "CUST-456"
        assert row["tray_details"] == "Mini — $500 — consignment"
        assert row["case_number"] == "REF-789"
        assert row["shipping_priority"] == "overnight"
        assert row["return_label_needed"] == "yes"
