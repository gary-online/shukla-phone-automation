import csv
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.csv_service import CSV_HEADERS, append_call_record
from src.types import CallRecord, Priority, RequestType


def _make_record(**overrides) -> CallRecord:
    defaults = dict(
        call_sid="CA123",
        timestamp="2026-03-13T12:00:00Z",
        rep_name="John Smith",
        request_type=RequestType.PPS_CASE_REPORT,
        tray_type="Mini",
        surgeon="Dr. Jones",
        facility="City Hospital",
        surgery_date="2026-03-15",
        details="Test case",
        priority=Priority.NORMAL,
        routed_to="pps-team@shuklamedical.com",
        call_duration_seconds=120,
    )
    defaults.update(overrides)
    return CallRecord(**defaults)


def test_creates_new_csv_with_header(tmp_path):
    csv_path = tmp_path / "call-records-2026-03.csv"
    with patch("src.csv_service._get_csv_path", return_value=csv_path):
        append_call_record(_make_record())

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
        append_call_record(_make_record(call_sid="CA001"))
        append_call_record(_make_record(call_sid="CA002"))

    with open(csv_path) as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == CSV_HEADERS
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0][0] == "CA001"
        assert rows[1][0] == "CA002"


def test_oserror_propagates(tmp_path):
    # Point to a path inside a non-existent read-only location
    bad_path = Path("/proc/nonexistent/call-records.csv")
    with patch("src.csv_service._get_csv_path", return_value=bad_path):
        with pytest.raises(OSError):
            append_call_record(_make_record())
