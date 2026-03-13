import asyncio
import logging
from datetime import datetime, timezone

from src.types import CallRecord, CallRecordExtract
from src.csv_service import append_call_record
from src.google_chat_service import send_google_chat_notification
from src.email_service import send_email_notification
from src.error_history import record_error

logger = logging.getLogger(__name__)


def _get_routing_destination(request_type: str) -> str:
    # Phase 1: Everything goes to the main team
    # Future: Route based on request type
    return "pps-team@shuklamedical.com"


async def process_completed_call(
    call_sid: str,
    extract: CallRecordExtract,
    call_duration_seconds: int,
) -> None:
    record = CallRecord(
        call_sid=call_sid,
        timestamp=datetime.now(timezone.utc).isoformat(),
        rep_name=extract.rep_name,
        request_type=extract.request_type,
        tray_type=extract.tray_type,
        surgeon=extract.surgeon,
        facility=extract.facility,
        facility_address=extract.facility_address,
        customer_id=extract.customer_id,
        tray_details=extract.tray_details,
        surgery_date=extract.surgery_date,
        details=extract.details,
        priority=extract.priority,
        routed_to=_get_routing_destination(extract.request_type),
        call_duration_seconds=call_duration_seconds,
        case_number=extract.case_number,
        sender_info=extract.sender_info,
        recipient_info=extract.recipient_info,
        shipping_priority=extract.shipping_priority,
        shipment_weight=extract.shipment_weight,
        return_label_needed=extract.return_label_needed,
    )

    logger.info("Processing completed call: call_sid=%s request_type=%s", call_sid, record.request_type)

    # Run all outputs concurrently — don't let one failure block others
    results = await asyncio.gather(
        _append_csv_safe(record),
        send_google_chat_notification(record),
        send_email_notification(record),
        return_exceptions=True,
    )

    service_names = ["CSV", "Google Chat", "Email"]
    for name, result in zip(service_names, results):
        if isinstance(result, Exception):
            logger.error("Output delivery failed for %s (call_sid=%s): %s", name, call_sid, result)
            record_error(call_sid, name.lower().replace(" ", "_"), str(result))


async def _append_csv_safe(record: CallRecord) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, append_call_record, record)
