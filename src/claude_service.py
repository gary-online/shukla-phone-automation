import json
import logging
from dataclasses import dataclass

import anthropic
import httpx

from src.config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, CLAUDE_MODEL, CLAUDE_TIMEOUT
from src.retry import with_retry
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
            "surgeon": {
                "type": "string",
                "description": "Surgeon/doctor name, or empty string if not applicable",
            },
            "facility": {
                "type": "string",
                "description": "Facility/hospital name",
            },
            "facility_address": {
                "type": "string",
                "description": "Facility/hospital address (street, city, state, zip)",
            },
            "customer_id": {
                "type": "string",
                "description": "Customer ID if provided, or empty string",
            },
            "trays": {
                "type": "array",
                "description": "List of trays involved in this request",
                "items": {
                    "type": "object",
                    "properties": {
                        "tray_type": {
                            "type": "string",
                            "description": "Tray type name from the catalog",
                        },
                        "price": {
                            "type": "string",
                            "description": "Price of the tray, e.g. '$500'",
                        },
                        "source": {
                            "type": "string",
                            "enum": ["consignment", "headquarters", ""],
                            "description": "Whether this tray is a consignment set (already with rep) or being requested from headquarters",
                        },
                    },
                    "required": ["tray_type"],
                },
            },
            "surgery_date": {
                "type": "string",
                "description": "Surgery date in YYYY-MM-DD format, or empty string",
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
            "case_number": {
                "type": "string",
                "description": "Case or reference number (for FedEx label requests)",
            },
            "sender_name": {
                "type": "string",
                "description": "Sender name (for FedEx label requests)",
            },
            "sender_company": {
                "type": "string",
                "description": "Sender company (for FedEx label requests)",
            },
            "sender_address": {
                "type": "string",
                "description": "Sender full address (for FedEx label requests)",
            },
            "sender_phone": {
                "type": "string",
                "description": "Sender phone number (for FedEx label requests)",
            },
            "sender_email": {
                "type": "string",
                "description": "Sender email (for FedEx label requests)",
            },
            "shipping_priority": {
                "type": "string",
                "enum": ["overnight", "second day", "ground", ""],
                "description": "Shipping priority (for FedEx label requests)",
            },
            "recipient_name": {
                "type": "string",
                "description": "Recipient name (for FedEx label requests)",
            },
            "recipient_company": {
                "type": "string",
                "description": "Recipient company (for FedEx label requests)",
            },
            "recipient_address": {
                "type": "string",
                "description": "Recipient full address (for FedEx label requests)",
            },
            "recipient_phone": {
                "type": "string",
                "description": "Recipient phone number (for FedEx label requests)",
            },
            "recipient_email": {
                "type": "string",
                "description": "Recipient email (for FedEx label requests)",
            },
            "shipment_weight": {
                "type": "string",
                "description": "Weight of the shipment (for FedEx label requests)",
            },
            "return_label_needed": {
                "type": "boolean",
                "description": "Whether a return label is needed (for FedEx label requests)",
            },
        },
        "required": ["rep_name", "request_type"],
    },
}


@dataclass
class ConversationTurn:
    role: str  # "user" or "assistant"
    content: str


TRANSFER_TOOL: anthropic.types.ToolParam = {
    "name": "transfer_to_human",
    "description": (
        "Transfer the caller to a human when you cannot help, the caller "
        "requests it, or the situation requires human judgment."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Brief reason why the transfer is needed",
            },
        },
        "required": ["reason"],
    },
}

TOOLS = [SUBMIT_TOOL, TRANSFER_TOOL]


@dataclass
class ClaudeResponse:
    text: str
    call_record: CallRecordExtract | None
    done: bool
    transfer_reason: str | None = None


def _format_trays(trays: list[dict]) -> tuple[str, str]:
    """Format trays list into tray_type summary and tray_details breakdown.

    Returns (tray_type, tray_details) tuple.
    """
    if not trays:
        return "", ""

    names = []
    details = []
    for t in trays:
        name = t.get("tray_type", "")
        if not name:
            continue
        names.append(name)
        parts = [name]
        if t.get("price"):
            parts.append(t["price"])
        if t.get("source"):
            parts.append(t["source"])
        details.append(" — ".join(parts))

    return ", ".join(names), "; ".join(details)


def _format_contact(inp: dict, prefix: str) -> str:
    """Format sender/recipient contact info into a single string."""
    parts = []
    for field in ["name", "company", "address", "phone", "email"]:
        val = inp.get(f"{prefix}_{field}", "")
        if val:
            parts.append(val)
    return ", ".join(parts)


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

    async def _call_claude():
        nonlocal full_text, tool_name, tool_id, tool_input_json
        full_text = ""
        tool_name = ""
        tool_id = ""
        tool_input_json = ""
        async with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
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

    await with_retry(_call_claude, max_attempts=3, base_delay=1.0)

    call_record = None
    done = False

    # Handle tool use (submit_call_record)
    if tool_name == "submit_call_record" and tool_input_json:
        try:
            inp = json.loads(tool_input_json)
        except json.JSONDecodeError:
            logger.error("Malformed tool input JSON: %s", tool_input_json)
            return ClaudeResponse(text=full_text, call_record=None, done=False)

        if not inp.get("rep_name", "").strip():
            logger.error("Empty rep_name in tool input")
            return ClaudeResponse(text=full_text, call_record=None, done=False)

        # Format structured tray info
        trays = inp.get("trays", [])
        tray_type, tray_details = _format_trays(trays)

        # Format sender/recipient info
        sender_info = _format_contact(inp, "sender")
        recipient_info = _format_contact(inp, "recipient")

        try:
            call_record = CallRecordExtract(
                rep_name=inp.get("rep_name", ""),
                request_type=RequestType(inp.get("request_type", "Other")),
                tray_type=tray_type,
                surgeon=inp.get("surgeon", ""),
                facility=inp.get("facility", ""),
                facility_address=inp.get("facility_address", ""),
                customer_id=inp.get("customer_id", ""),
                tray_details=tray_details,
                surgery_date=inp.get("surgery_date", ""),
                details=inp.get("details", ""),
                priority=Priority(inp.get("priority", "normal")),
                case_number=inp.get("case_number", ""),
                sender_info=sender_info,
                recipient_info=recipient_info,
                shipping_priority=inp.get("shipping_priority", ""),
                shipment_weight=inp.get("shipment_weight", ""),
                return_label_needed="yes" if inp.get("return_label_needed") else "",
            )
        except (ValueError, KeyError) as e:
            logger.error("Invalid tool input values: %s", e)
            return ClaudeResponse(text=full_text, call_record=None, done=False)

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

        try:
            async with client.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=200,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            ) as follow_stream:
                async for event in follow_stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        full_text += event.delta.text
        except Exception as e:
            logger.warning("Follow-up stream failed, using fallback: %s", e)
            if not full_text:
                full_text = "Got it, I've sent this to the team. Thank you for calling."

    elif tool_name == "transfer_to_human" and tool_input_json:
        try:
            inp = json.loads(tool_input_json)
        except json.JSONDecodeError:
            inp = {"reason": "unknown"}
        reason = inp.get("reason", "unknown")
        logger.warning("Claude requested transfer to human: %s", reason)

        messages.append({"role": "assistant", "content": [
            *([{"type": "text", "text": full_text}] if full_text else []),
            {"type": "tool_use", "id": tool_id, "name": tool_name, "input": inp},
        ]})
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": "Transfer noted. A team member will follow up.",
            }],
        })

        try:
            async with client.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=100,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            ) as follow_stream:
                async for event in follow_stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        full_text += event.delta.text
        except Exception as e:
            logger.warning("Follow-up stream failed, using fallback: %s", e)
            if not full_text:
                full_text = "I'm going to have one of our team members follow up with you. Thank you for calling."

        return ClaudeResponse(text=full_text, call_record=None, done=True, transfer_reason=reason)

    return ClaudeResponse(text=full_text, call_record=call_record, done=done)
