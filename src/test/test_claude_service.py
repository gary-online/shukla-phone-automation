import json
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from src.claude_service import ConversationTurn, get_claude_response


class MockStream:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.events:
            raise StopAsyncIteration
        return self.events.pop(0)


@dataclass
class ContentBlockStart:
    type: str = "content_block_start"
    content_block: object = None


@dataclass
class ContentBlockDelta:
    type: str = "content_block_delta"
    delta: object = None


@dataclass
class ToolUseBlock:
    type: str = "tool_use"
    name: str = ""
    id: str = ""


@dataclass
class TextDelta:
    type: str = "text_delta"
    text: str = ""


@dataclass
class InputJsonDelta:
    type: str = "input_json_delta"
    partial_json: str = ""


def _make_tool_events(tool_input: str, text: str = "Here's your confirmation."):
    """Build stream events: text block + tool_use block."""
    events = []
    if text:
        events.append(ContentBlockDelta(delta=TextDelta(text=text)))
    events.append(ContentBlockStart(content_block=ToolUseBlock(
        type="tool_use", name="submit_call_record", id="tool_123"
    )))
    events.append(ContentBlockDelta(delta=InputJsonDelta(partial_json=tool_input)))
    return events


VALID_TOOL_INPUT = json.dumps({
    "rep_name": "John Smith",
    "request_type": "PPS Case Report",
    "trays": [
        {"tray_type": "Mini", "price": "$500", "source": "consignment"},
    ],
    "surgeon": "Dr. Jones",
    "facility": "City Hospital",
    "surgery_date": "2026-03-15",
    "details": "Standard case",
    "priority": "normal",
})


@pytest.mark.asyncio
async def test_malformed_json():
    events = _make_tool_events("{bad json")
    history = [ConversationTurn(role="user", content="test")]

    with patch("src.claude_service.client") as mock_client:
        mock_client.messages.stream.return_value = MockStream(events)
        result = await get_claude_response(history)

    assert result.call_record is None
    assert result.done is False


@pytest.mark.asyncio
async def test_invalid_request_type():
    bad_input = json.dumps({
        "rep_name": "John",
        "request_type": "INVALID_TYPE",
    })
    events = _make_tool_events(bad_input)
    history = [ConversationTurn(role="user", content="test")]

    with patch("src.claude_service.client") as mock_client:
        mock_client.messages.stream.return_value = MockStream(events)
        result = await get_claude_response(history)

    assert result.call_record is None
    assert result.done is False


@pytest.mark.asyncio
async def test_empty_rep_name():
    bad_input = json.dumps({
        "rep_name": "",
        "request_type": "Other",
    })
    events = _make_tool_events(bad_input)
    history = [ConversationTurn(role="user", content="test")]

    with patch("src.claude_service.client") as mock_client:
        mock_client.messages.stream.return_value = MockStream(events)
        result = await get_claude_response(history)

    assert result.call_record is None
    assert result.done is False


@pytest.mark.asyncio
async def test_valid_tool_input():
    events = _make_tool_events(VALID_TOOL_INPUT, text="Confirmed.")

    # The follow-up stream for closing message
    follow_events = [ContentBlockDelta(delta=TextDelta(text="Thanks for calling!"))]

    history = [ConversationTurn(role="user", content="test")]

    with patch("src.claude_service.client") as mock_client:
        # First call returns tool use events, second call returns closing message
        mock_client.messages.stream.side_effect = [
            MockStream(events),
            MockStream(follow_events),
        ]
        result = await get_claude_response(history)

    assert result.call_record is not None
    assert result.call_record.rep_name == "John Smith"
    assert result.call_record.request_type == "PPS Case Report"
    assert result.call_record.tray_type == "Mini"
    assert result.call_record.tray_details == "Mini — $500 — consignment"
    assert result.done is True
    assert "Thanks for calling!" in result.text


@pytest.mark.asyncio
async def test_tray_formatting():
    """Verify multi-tray input is formatted correctly."""
    tool_input = json.dumps({
        "rep_name": "Gary",
        "request_type": "Bill Only Request",
        "trays": [
            {"tray_type": "Mini", "price": "$500", "source": "consignment"},
            {"tray_type": "Blade", "price": "$300", "source": "headquarters"},
        ],
        "surgeon": "Dr. Smith",
        "facility": "Test Hospital",
    })
    events = _make_tool_events(tool_input, text="Confirmed.")
    follow_events = [ContentBlockDelta(delta=TextDelta(text="Done."))]
    history = [ConversationTurn(role="user", content="test")]

    with patch("src.claude_service.client") as mock_client:
        mock_client.messages.stream.side_effect = [
            MockStream(events),
            MockStream(follow_events),
        ]
        result = await get_claude_response(history)

    assert result.call_record is not None
    assert result.call_record.tray_type == "Mini, Blade"
    assert "Mini — $500 — consignment" in result.call_record.tray_details
    assert "Blade — $300 — headquarters" in result.call_record.tray_details
