import pytest
from unittest.mock import patch, AsyncMock

from src.call_processor import process_completed_call
from src.types import CallRecordExtract, RequestType, Priority


def _make_extract(**overrides) -> CallRecordExtract:
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


@pytest.mark.asyncio
async def test_all_outputs_called():
    with patch("src.call_processor.append_call_record") as mock_csv, \
         patch("src.call_processor.send_google_chat_notification", new_callable=AsyncMock) as mock_chat, \
         patch("src.call_processor.send_email_notification", new_callable=AsyncMock) as mock_email:

        await process_completed_call("CA_test", _make_extract(), 120)

        mock_csv.assert_called_once()
        mock_chat.assert_called_once()
        mock_email.assert_called_once()


@pytest.mark.asyncio
async def test_one_failure_does_not_block_others():
    with patch("src.call_processor.append_call_record", side_effect=OSError("disk full")), \
         patch("src.call_processor.send_google_chat_notification", new_callable=AsyncMock) as mock_chat, \
         patch("src.call_processor.send_email_notification", new_callable=AsyncMock) as mock_email:

        await process_completed_call("CA_test", _make_extract(), 120)

        mock_chat.assert_called_once()
        mock_email.assert_called_once()
