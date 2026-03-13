import pytest
from pydantic import ValidationError

from src.types import (
    CallRecord,
    CallRecordExtract,
    Priority,
    RequestType,
    TRAY_CATALOG,
)


class TestStrEnumValues:
    def test_request_type_str_returns_value(self):
        assert str(RequestType.PPS_CASE_REPORT) == "PPS Case Report"
        assert str(RequestType.FEDEX_LABEL_REQUEST) == "FedEx Label Request"
        assert str(RequestType.OTHER) == "Other"

    def test_priority_str_returns_value(self):
        assert str(Priority.NORMAL) == "normal"
        assert str(Priority.URGENT) == "urgent"

    def test_request_type_from_value(self):
        assert RequestType("PPS Case Report") == RequestType.PPS_CASE_REPORT

    def test_priority_from_value(self):
        assert Priority("urgent") == Priority.URGENT

    def test_invalid_request_type_raises(self):
        with pytest.raises(ValueError):
            RequestType("INVALID")

    def test_invalid_priority_raises(self):
        with pytest.raises(ValueError):
            Priority("critical")


class TestCallRecordExtract:
    def test_valid_extract(self):
        extract = CallRecordExtract(
            rep_name="John Smith",
            request_type=RequestType.PPS_CASE_REPORT,
        )
        assert extract.rep_name == "John Smith"
        assert extract.request_type == RequestType.PPS_CASE_REPORT
        assert extract.priority == Priority.NORMAL
        assert extract.tray_type == ""
        assert extract.surgeon == ""

    def test_defaults(self):
        extract = CallRecordExtract(
            rep_name="Jane",
            request_type=RequestType.OTHER,
        )
        assert extract.tray_type == ""
        assert extract.surgeon == ""
        assert extract.facility == ""
        assert extract.surgery_date == ""
        assert extract.details == ""
        assert extract.priority == Priority.NORMAL
        assert extract.facility_address == ""
        assert extract.customer_id == ""
        assert extract.tray_details == ""
        assert extract.case_number == ""
        assert extract.sender_info == ""
        assert extract.recipient_info == ""
        assert extract.shipping_priority == ""

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            CallRecordExtract(rep_name="John")  # missing request_type

    def test_new_fields(self):
        extract = CallRecordExtract(
            rep_name="Gary",
            request_type=RequestType.BILL_ONLY_REQUEST,
            facility_address="123 Main St, Dallas TX",
            customer_id="CUST-123",
            tray_details="Mini — $500 — consignment",
        )
        assert extract.facility_address == "123 Main St, Dallas TX"
        assert extract.customer_id == "CUST-123"
        assert extract.tray_details == "Mini — $500 — consignment"


class TestCallRecord:
    def test_valid_record(self):
        record = CallRecord(
            call_sid="CA123",
            timestamp="2026-03-13T12:00:00Z",
            rep_name="John",
            request_type=RequestType.OTHER,
        )
        assert record.call_sid == "CA123"
        assert record.call_duration_seconds == 0
        assert record.routed_to == ""

    def test_defaults(self):
        record = CallRecord(
            call_sid="CA123",
            timestamp="2026-03-13T12:00:00Z",
            rep_name="John",
            request_type=RequestType.OTHER,
        )
        assert record.tray_type == ""
        assert record.priority == Priority.NORMAL
        assert record.call_duration_seconds == 0
        assert record.facility_address == ""
        assert record.customer_id == ""
        assert record.tray_details == ""
        assert record.case_number == ""

    def test_fedex_fields(self):
        record = CallRecord(
            call_sid="CA123",
            timestamp="2026-03-13T12:00:00Z",
            rep_name="Gary",
            request_type=RequestType.FEDEX_LABEL_REQUEST,
            case_number="REF-999",
            sender_info="John, Acme, 123 Main St",
            recipient_info="Jane, Hospital, 456 Oak Ave",
            shipping_priority="overnight",
            shipment_weight="15 lbs",
            return_label_needed="yes",
        )
        assert record.case_number == "REF-999"
        assert record.shipping_priority == "overnight"
        assert record.return_label_needed == "yes"


class TestTrayCatalog:
    def test_catalog_not_empty(self):
        assert len(TRAY_CATALOG) > 0

    def test_known_trays_present(self):
        assert "Mini" in TRAY_CATALOG
        assert "Maxi" in TRAY_CATALOG
        assert "Hip" in TRAY_CATALOG
