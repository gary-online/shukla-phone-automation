import logging
from dataclasses import dataclass

import anthropic

from src.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from src.system_prompt import SYSTEM_PROMPT
from src.types import CallRecordExtract, Priority, RequestType

logger = logging.getLogger(__name__)

client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

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
    messages = [{"role": t.role, "content": t.content} for t in conversation_history]

    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        tools=[SUBMIT_TOOL],
        messages=messages,
    )

    text = ""
    call_record = None
    done = False

    for block in response.content:
        if block.type == "text":
            text += block.text
        elif block.type == "tool_use" and block.name == "submit_call_record":
            inp = block.input
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

            # Send tool result back to get the closing message
            messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Record submitted successfully. The team has been notified.",
                        }
                    ],
                }
            )

            follow_up = await client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=200,
                system=SYSTEM_PROMPT,
                tools=[SUBMIT_TOOL],
                messages=messages,
            )

            for follow_block in follow_up.content:
                if follow_block.type == "text":
                    text += follow_block.text

    return ClaudeResponse(text=text, call_record=call_record, done=done)
