from src.types import CallRecord, CallRecordExtract, Priority, RequestType


def make_record(**overrides) -> CallRecord:
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


def make_extract(**overrides) -> CallRecordExtract:
    defaults = {
        "rep_name": "Gary",
        "request_type": RequestType.BILL_ONLY_REQUEST,
        "tray_type": "Mini",
        "surgeon": "Dr. Smith",
        "facility": "Test Hospital",
        "surgery_date": "2026-03-20",
        "details": "Test",
        "priority": Priority.NORMAL,
    }
    defaults.update(overrides)
    return CallRecordExtract(**defaults)
