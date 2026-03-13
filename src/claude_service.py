import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import anthropic
import httpx

from src.config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, CLAUDE_MODEL, CLAUDE_TIMEOUT
from src.system_prompt import SYSTEM_PROMPT
from src.types import CallRecordExtract, Priority, RequestType

logger = logging.getLogger(__name__)

client = anthropic.AsyncAnthropic(
    api_key=ANTHROPIC_API_KEY,
    timeout=httpx.Timeout(CLAUDE_TIMEOUT, connect=10.0),
    **({"base_url": ANTHROPIC_BASE_URL} if ANTHROPIC_BASE_URL else {}),
)

SUBMIT_TOOL: anthropic.types.ToolParam = {
    "name": "submit_call_record",
    "description": (
        "Submit the structured call record after the caller confirms the "
        "information is correct. Call this tool once all information has been "
        "collected and confirmed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "rep_name": {
                "type": "string",
                "description": "Name of the sales representative calling",
            },
            "request_type": {
                "type": "string",
                "enum": [rt.value for rt in RequestType],
                "description": "Type of request",
            },
            "tray_type": {
                "type": "string",
                "description": "Tray type from the catalog, or empty string if not applicable",
            },
            "surgeon": {
                "type": "string",
                "description": "Surgeon/doctor name, or empty string if not applicable",
            },
            "facility": {
                "type": "string",
                "description": "Facility/hospital name, or empty string if not applicable",
            },
            "surgery_date": {
                "type": "string",
                "description": "Surgery date in YYYY-MM-DD format, or empty string if not applicable",
            },
            "details": {
                "type": "string",
                "description": "Additional details, summary, or notes about the request",
            },
            "priority": {
                "type": "string",
                "enum": [p.value for p in Priority],
                "description": "Priority level — urgent only if caller explicitly says so",
            },
        },
        "required": [
            "rep_name",
            "request_type",
            "tray_type",
            "surgeon",
            "facility",
            "surgery_date",
            "details",
            "priority",
        ],
    },
}


@dataclass
class ConversationTurn:
    role: str  # "user" or "assistant"
    content: str


@dataclass
class ClaudeResponse:
    text: str
    call_record: CallRecordExtract | None
    done: bool


async def get_claude_response(
    conversation_history: list[ConversationTurn],
) -> ClaudeResponse:
    """Get Claude's response using streaming for faster time-to-completion.

    Returns the full response text and optional call record.
    Uses streaming internally but collects the full response before returning,
    so TTS gets a complete utterance without fragmentation issues.
    """
    messages = [{"role": t.role, "content": t.content} for t in conversation_history]

    full_text = ""
    tool_name = ""
    tool_id = ""
    tool_input_json = ""

    async with client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        tools=[SUBMIT_TOOL],
        messages=messages,
    ) as stream:
        async for event in stream:
            if event.type == "content_block_start":
                if event.content_block.type == "tool_use":
                    tool_name = event.content_block.name
                    tool_id = event.content_block.id
            elif event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    full_text += event.delta.text
                elif event.delta.type == "input_json_delta":
                    tool_input_json += event.delta.partial_json

    call_record = None
    done = False

    # Handle tool use (submit_call_record)
    if tool_name == "submit_call_record" and tool_input_json:
        inp = json.loads(tool_input_json)
        call_record = CallRecordExtract(
            rep_name=inp.get("rep_name", ""),
            request_type=RequestType(inp.get("request_type", "Other")),
            tray_type=inp.get("tray_type", ""),
            surgeon=inp.get("surgeon", ""),
            facility=inp.get("facility", ""),
            surgery_date=inp.get("surgery_date", ""),
            details=inp.get("details", ""),
            priority=Priority(inp.get("priority", "normal")),
        )
        done = True
        logger.info("Claude submitted call record via tool use: %s", call_record)

        # Get closing message after tool use
        messages.append({"role": "assistant", "content": [
            *([{"type": "text", "text": full_text}] if full_text else []),
            {"type": "tool_use", "id": tool_id, "name": tool_name, "input": inp},
        ]})

        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": "Record submitted successfully. The team has been notified.",
            }],
        })

        async with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=200,
            system=SYSTEM_PROMPT,
            tools=[SUBMIT_TOOL],
            messages=messages,
        ) as follow_stream:
            async for event in follow_stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    full_text += event.delta.text

    return ClaudeResponse(text=full_text, call_record=call_record, done=done)
