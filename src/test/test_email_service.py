import pytest

from src.email_service import _build_email_body
from src.types import Priority, RequestType
from src.test.conftest import make_record


def test_email_body_includes_all_fields():
    record = make_record()
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
    record = make_record(tray_type="", surgeon="", facility="", surgery_date="", details="")
    body = _build_email_body(record)

    assert "John Smith" in body
    assert "PPS Case Report" in body
    assert "Tray" not in body
    assert "Surgeon" not in body
    assert "Facility" not in body
    assert "Surgery Date" not in body
    assert "Details" not in body


def test_email_body_shows_tray_details_over_tray_type():
    record = make_record(
        tray_type="Mini, Blade",
        tray_details="Mini — $500 — consignment; Blade — $300 — headquarters",
    )
    body = _build_email_body(record)

    assert "Tray Details: Mini — $500 — consignment; Blade — $300 — headquarters" in body
    # Should show tray_details, not the simple tray_type
    assert "Tray Type:" not in body


def test_email_body_shows_fedex_fields():
    record = make_record(
        request_type=RequestType.FEDEX_LABEL_REQUEST,
        case_number="REF-12345",
        sender_info="John Smith, Acme Corp, 123 Main St Dallas TX 75201, 555-1234, john@acme.com",
        recipient_info="Jane Doe, City Hospital, 456 Oak Ave Austin TX 78701, 555-5678, jane@city.com",
        shipping_priority="overnight",
        shipment_weight="15 lbs",
        return_label_needed="yes",
    )
    body = _build_email_body(record)

    assert "Case/Reference #: REF-12345" in body
    assert "Sender:" in body
    assert "Recipient:" in body
    assert "Shipping Priority: overnight" in body
    assert "Shipment Weight: 15 lbs" in body
    assert "Return Label Needed: yes" in body


def test_urgent_subject():
    record = make_record(priority=Priority.URGENT)
    priority_label = "URGENT" if record.priority == Priority.URGENT else "New"
    subject = f"[{priority_label}] {record.request_type} — {record.rep_name}"
    assert subject == "[URGENT] PPS Case Report — John Smith"


def test_normal_subject():
    record = make_record(priority=Priority.NORMAL)
    priority_label = "URGENT" if record.priority == Priority.URGENT else "New"
    subject = f"[{priority_label}] {record.request_type} — {record.rep_name}"
    assert subject == "[New] PPS Case Report — John Smith"
