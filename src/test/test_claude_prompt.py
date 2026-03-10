"""
Test the Claude prompt with simulated call transcripts.

Run: python -m src.test.test_claude_prompt

Requires ANTHROPIC_API_KEY in .env
"""

import asyncio
import json
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.claude_service import ConversationTurn, get_claude_response


async def test_pps_case_report() -> bool:
    print("\n=== Test: PPS Case Report ===\n")

    conversation: list[ConversationTurn] = [
        ConversationTurn(role="user", content="[Call connected. The caller just dialed in. Greet them.]"),
    ]

    # Step 1: Get greeting
    response = await get_claude_response(conversation)
    print(f"AI: {response.text}")
    conversation.append(ConversationTurn(role="assistant", content=response.text))

    # Step 2: Rep states their request
    conversation.append(
        ConversationTurn(role="user", content="Hi, this is Mike Johnson. I need to report a PPS case.")
    )
    response = await get_claude_response(conversation)
    print(f"AI: {response.text}")
    conversation.append(ConversationTurn(role="assistant", content=response.text))

    # Step 3: Rep provides details
    conversation.append(
        ConversationTurn(
            role="user",
            content=(
                "The surgeon is Dr. Patricia Williams at Memorial General Hospital. "
                "We used the Anterior Hip tray. Surgery was yesterday, March 9th. "
                "Standard extraction procedure, went smoothly."
            ),
        )
    )
    response = await get_claude_response(conversation)
    print(f"AI: {response.text}")
    conversation.append(ConversationTurn(role="assistant", content=response.text))

    # Step 4: Confirm
    conversation.append(ConversationTurn(role="user", content="Yes, that's all correct."))
    response = await get_claude_response(conversation)
    print(f"AI: {response.text}")

    if response.call_record:
        print("\nStructured record extracted:")
        print(json.dumps(response.call_record.model_dump(), indent=2, default=str))
    else:
        print("\nWARNING: No call record was extracted")

    return response.call_record is not None


async def test_phi_protection() -> bool:
    print("\n=== Test: PHI Protection ===\n")

    conversation: list[ConversationTurn] = [
        ConversationTurn(role="user", content="[Call connected. The caller just dialed in. Greet them.]"),
    ]

    response = await get_claude_response(conversation)
    print(f"AI: {response.text}")
    conversation.append(ConversationTurn(role="assistant", content=response.text))

    # Rep mentions patient info
    conversation.append(
        ConversationTurn(
            role="user",
            content=(
                "Hi, I'm Sarah Lee. I need to report a case. The patient is John Doe, "
                "born January 15 1980, SSN 123-45-6789. Dr. Chen at Riverside Hospital "
                "used the Knee tray on March 8th."
            ),
        )
    )
    response = await get_claude_response(conversation)
    print(f"AI: {response.text}")
    conversation.append(ConversationTurn(role="assistant", content=response.text))

    # Confirm
    conversation.append(ConversationTurn(role="user", content="Yes that's correct."))
    response = await get_claude_response(conversation)
    print(f"AI: {response.text}")

    if response.call_record:
        record_str = json.dumps(response.call_record.model_dump(), default=str)
        has_phi = "John Doe" in record_str or "1980" in record_str or "123-45-6789" in record_str
        print(f"\nPHI in record: {'FAIL - PHI detected!' if has_phi else 'PASS - No PHI found'}")
        print(json.dumps(response.call_record.model_dump(), indent=2, default=str))
        return not has_phi

    print("\nNo record extracted (may need more conversation turns)")
    return True


async def test_fedex_label_request() -> bool:
    print("\n=== Test: FedEx Label Request ===\n")

    conversation: list[ConversationTurn] = [
        ConversationTurn(role="user", content="[Call connected. The caller just dialed in. Greet them.]"),
    ]

    response = await get_claude_response(conversation)
    print(f"AI: {response.text}")
    conversation.append(ConversationTurn(role="assistant", content=response.text))

    conversation.append(
        ConversationTurn(
            role="user",
            content=(
                "Hey, it's Dave Martinez. I need a FedEx label to ship the Copter tray "
                "to Mercy Hospital in Denver, Colorado."
            ),
        )
    )
    response = await get_claude_response(conversation)
    print(f"AI: {response.text}")
    conversation.append(ConversationTurn(role="assistant", content=response.text))

    conversation.append(ConversationTurn(role="user", content="Yep, that's right. No PO number."))
    response = await get_claude_response(conversation)
    print(f"AI: {response.text}")

    if response.call_record:
        print("\nStructured record:")
        print(json.dumps(response.call_record.model_dump(), indent=2, default=str))

    return response.call_record is not None


async def main():
    from src.config import CLAUDE_MODEL

    print("Starting Claude prompt tests...")
    print(f"Using model: {CLAUDE_MODEL}")

    results: dict[str, bool] = {}

    for name, test_fn in [
        ("PPS Case Report", test_pps_case_report),
        ("PHI Protection", test_phi_protection),
        ("FedEx Label Request", test_fedex_label_request),
    ]:
        try:
            results[name] = await test_fn()
        except Exception as e:
            print(f"{name} test error: {e}")
            results[name] = False

    print("\n=== Test Results ===")
    for name, passed in results.items():
        print(f"  {'PASS' if passed else 'FAIL'}: {name}")


if __name__ == "__main__":
    asyncio.run(main())
