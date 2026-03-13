import pytest

from src.email_service import _build_email_body
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
        details="Standard case",
        priority=Priority.NORMAL,
        routed_to="pps-team@shuklamedical.com",
        call_duration_seconds=120,
    )
    defaults.update(overrides)
    return CallRecord(**defaults)


def test_email_body_includes_all_fields():
    record = _make_record()
    body = _build_email_body(record)

    assert "John Smith" in body
    assert "PPS Case Report" in body
    assert "Mini" in body
    assert "Dr. Jones" in body
    assert "City Hospital" in body
    assert "2026-03-15" in body
    assert "Standard case" in body
    assert "CA123" in body


def test_email_body_omits_empty_optional_fields():
    record = _make_record(tray_type="", surgeon="", facility="", surgery_date="", details="")
    body = _build_email_body(record)

    assert "John Smith" in body
    assert "PPS Case Report" in body
    assert "Tray Type" not in body
    assert "Surgeon" not in body
    assert "Facility" not in body
    assert "Surgery Date" not in body
    assert "Details" not in body


def test_urgent_subject():
    record = _make_record(priority=Priority.URGENT)
    priority_label = "URGENT" if record.priority == Priority.URGENT else "New"
    subject = f"[{priority_label}] {record.request_type} — {record.rep_name}"
    assert subject == "[URGENT] PPS Case Report — John Smith"


def test_normal_subject():
    record = _make_record(priority=Priority.NORMAL)
    priority_label = "URGENT" if record.priority == Priority.URGENT else "New"
    subject = f"[{priority_label}] {record.request_type} — {record.rep_name}"
    assert subject == "[New] PPS Case Report — John Smith"
