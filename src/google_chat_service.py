import logging

import httpx

from src.config import GOOGLE_CHAT_WEBHOOK_URL
from src.retry import with_retry
from src.types import CallRecord

logger = logging.getLogger(__name__)


async def send_google_chat_notification(record: CallRecord) -> None:
    if not GOOGLE_CHAT_WEBHOOK_URL:
        logger.warning("Google Chat webhook URL not configured, skipping notification")
        return

    widgets = []
    if record.tray_type:
        widgets.append({"keyValue": {"topLabel": "Tray Type", "content": record.tray_type}})
    if record.surgeon:
        widgets.append({"keyValue": {"topLabel": "Surgeon", "content": record.surgeon}})
    if record.facility:
        widgets.append({"keyValue": {"topLabel": "Facility", "content": record.facility}})
    if record.surgery_date:
        widgets.append({"keyValue": {"topLabel": "Surgery Date", "content": record.surgery_date}})
    widgets.append({"keyValue": {"topLabel": "Priority", "content": str(record.priority).upper()}})
    if record.details:
        widgets.append({"textParagraph": {"text": f"<b>Details:</b> {record.details}"}})

    card = {
        "cards": [
            {
                "header": {
                    "title": f"New {record.request_type}",
                    "subtitle": f"From: {record.rep_name}",
                },
                "sections": [{"widgets": widgets}],
            }
        ]
    }

    async def _post_chat():
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            response = await http_client.post(
                GOOGLE_CHAT_WEBHOOK_URL,
                json=card,
                headers={"Content-Type": "application/json"},
            )

        if response.status_code >= 400:
            logger.error(
                "Failed to send Google Chat notification: %s %s",
                response.status_code,
                response.text,
            )
        else:
            logger.info("Google Chat notification sent (call_sid=%s)", record.call_sid)

    try:
        await with_retry(_post_chat, max_attempts=3, base_delay=1.0)
    except httpx.HTTPError as e:
        logger.error("Google Chat HTTP error (call_sid=%s): %s", record.call_sid, e)
        raise
