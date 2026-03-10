from enum import StrEnum
from pydantic import BaseModel


class RequestType(StrEnum):
    PPS_CASE_REPORT = "PPS Case Report"
    FEDEX_LABEL_REQUEST = "FedEx Label Request"
    BILL_ONLY_REQUEST = "Bill Only Request"
    TRAY_AVAILABILITY = "Tray Availability"
    DELIVERY_STATUS = "Delivery Status"
    OTHER = "Other"


class Priority(StrEnum):
    NORMAL = "normal"
    URGENT = "urgent"


TRAY_CATALOG = [
    "Mini",
    "Maxi",
    "Blade",
    "Shoulder-Blade",
    "Modular Hip",
    "Copter",
    "Broken Nail",
    "Lag",
    "Screw-Flex",
    "Anterior Hip",
    "Vise",
    "Screw",
    "Hip",
    "Knee",
    "Nail",
    "Spine-Cervical",
    "Spine-Thoracic & Lumbar",
    "Spine-Instruments",
    "Shoulder",
    "Trephine",
    "Cup",
    "Cement",
]


class CallRecord(BaseModel):
    call_sid: str
    timestamp: str
    rep_name: str
    request_type: RequestType
    tray_type: str = ""
    surgeon: str = ""
    facility: str = ""
    surgery_date: str = ""
    details: str = ""
    priority: Priority = Priority.NORMAL
    routed_to: str = ""
    call_duration_seconds: int = 0


class CallRecordExtract(BaseModel):
    """Fields extracted by Claude via tool use (before we add call metadata)."""

    rep_name: str
    request_type: RequestType
    tray_type: str = ""
    surgeon: str = ""
    facility: str = ""
    surgery_date: str = ""
    details: str = ""
    priority: Priority = Priority.NORMAL
