import asyncio
import base64
import logging
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.config import (
    GMAIL_FROM_ADDRESS,
    GMAIL_TO_ADDRESS,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REFRESH_TOKEN,
)
from src.csv_service import _get_csv_path
from src.retry import with_retry
from src.types import CallRecord, Priority

logger = logging.getLogger(__name__)


def _get_gmail_service():
    creds = Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
    )
    creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def _build_email_body(record: CallRecord) -> str:
    lines = [
        f"New {record.request_type}",
        "=" * 40,
        "",
        f"Timestamp: {record.timestamp}",
        f"Rep Name: {record.rep_name}",
        f"Request Type: {record.request_type}",
    ]

    if record.tray_type:
        lines.append(f"Tray Type: {record.tray_type}")
    if record.surgeon:
        lines.append(f"Surgeon: {record.surgeon}")
    if record.facility:
        lines.append(f"Facility: {record.facility}")
    if record.surgery_date:
        lines.append(f"Surgery Date: {record.surgery_date}")
    if record.details:
        lines.extend(["", "Details:", record.details])
    lines.extend(["", f"Priority: {str(record.priority).upper()}", f"Call SID: {record.call_sid}"])

    return "\n".join(lines)


async def send_email_notification(record: CallRecord) -> None:
    if not GOOGLE_CLIENT_ID or not GOOGLE_REFRESH_TOKEN:
        logger.warning("Gmail API not configured, skipping email notification")
        return

    priority_label = "URGENT" if record.priority == Priority.URGENT else "New"
    subject = f"[{priority_label}] {record.request_type} — {record.rep_name}"
    body = _build_email_body(record)

    message = MIMEMultipart()
    message["to"] = GMAIL_TO_ADDRESS
    message["from"] = GMAIL_FROM_ADDRESS
    message["subject"] = subject
    message.attach(MIMEText(body))

    # Attach the current month's CSV file if it exists
    csv_path = _get_csv_path()
    if csv_path.exists():
        with open(csv_path, "rb") as f:
            attachment = MIMEBase("text", "csv")
            attachment.set_payload(f.read())
            encoders.encode_base64(attachment)
            attachment.add_header(
                "Content-Disposition",
                f"attachment; filename={csv_path.name}",
            )
            message.attach(attachment)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    # Run sync Gmail API call in executor with per-attempt timeout and retry
    loop = asyncio.get_running_loop()

    async def _send_with_timeout():
        return await asyncio.wait_for(
            loop.run_in_executor(None, _send_gmail_message, raw),
            timeout=15.0,
        )

    try:
        await with_retry(_send_with_timeout, max_attempts=2, base_delay=2.0)
    except TimeoutError:
        logger.error("Email send timed out (call_sid=%s)", record.call_sid)
        raise
    except Exception as e:
        logger.error("Email send failed (call_sid=%s): %s", record.call_sid, e)
        raise

    logger.info("Email notification sent (call_sid=%s, to=%s)", record.call_sid, GMAIL_TO_ADDRESS)


async def send_escalation_email(
    call_sid: str,
    rep_name: str,
    reason: str,
    timestamp: str,
) -> None:
    if not GOOGLE_CLIENT_ID or not GOOGLE_REFRESH_TOKEN:
        logger.warning("Gmail API not configured, skipping escalation email")
        return

    subject = f"[ESCALATION] Call from {rep_name or 'unknown'} — {reason}"
    body = "\n".join([
        "Call Escalation",
        "=" * 40,
        "",
        f"Timestamp: {timestamp}",
        f"Rep Name: {rep_name or 'unknown'}",
        f"Reason: {reason}",
        f"Call SID: {call_sid}",
        "",
        "A team member should follow up with this caller.",
    ])

    message = MIMEText(body)
    message["to"] = GMAIL_TO_ADDRESS
    message["from"] = GMAIL_FROM_ADDRESS
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(None, _send_gmail_message, raw),
            timeout=15.0,
        )
        logger.info("Escalation email sent (call_sid=%s, to=%s)", call_sid, GMAIL_TO_ADDRESS)
    except Exception as e:
        logger.error("Escalation email failed (call_sid=%s): %s", call_sid, e)


def _send_gmail_message(raw: str) -> None:
    try:
        service = _get_gmail_service()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except Exception as e:
        logger.error("Gmail API error: %s", e)
        raise
