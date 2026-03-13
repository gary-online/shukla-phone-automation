import pytest
from unittest.mock import patch, AsyncMock

from src.google_chat_service import send_google_chat_notification
from src.test.conftest import make_record


@pytest.mark.asyncio
async def test_skips_when_no_webhook():
    with patch("src.google_chat_service.GOOGLE_CHAT_WEBHOOK_URL", ""):
        # Should not raise, just log and return
        await send_google_chat_notification(make_record())


@pytest.mark.asyncio
async def test_card_omits_empty_fields():
    """Verify that empty optional fields are not included in the card widgets."""
    record = make_record(tray_type="", surgeon="", facility="", surgery_date="", details="")
    captured_json = {}

    async def mock_post(url, json=None, headers=None):
        captured_json.update(json)
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        return mock_resp

    with patch("src.google_chat_service.GOOGLE_CHAT_WEBHOOK_URL", "https://example.com/webhook"):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = mock_post
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            await send_google_chat_notification(record)

    widgets = captured_json["cards"][0]["sections"][0]["widgets"]
    labels = []
    for w in widgets:
        if "keyValue" in w:
            labels.append(w["keyValue"]["topLabel"])

    assert "Tray Type" not in labels
    assert "Surgeon" not in labels
    assert "Facility" not in labels
    assert "Surgery Date" not in labels
    assert "Priority" in labels
