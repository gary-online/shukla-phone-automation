from src.claude_service import ConversationTurn
from src.websocket_handler import CallSession, MAX_HISTORY


def test_trim_history_no_op_under_limit():
    session = CallSession()
    for i in range(MAX_HISTORY):
        session.conversation_history.append(
            ConversationTurn(role="user", content=f"msg {i}")
        )
    assert len(session.conversation_history) == MAX_HISTORY
    session.trim_history()
    assert len(session.conversation_history) == MAX_HISTORY


def test_trim_history_keeps_first_and_last():
    session = CallSession()
    for i in range(30):
        role = "user" if i % 2 == 0 else "assistant"
        session.conversation_history.append(
            ConversationTurn(role=role, content=f"msg {i}")
        )
    assert len(session.conversation_history) == 30

    session.trim_history()
    assert len(session.conversation_history) == MAX_HISTORY

    # First turn preserved
    assert session.conversation_history[0].content == "msg 0"

    # Last turn preserved
    assert session.conversation_history[-1].content == "msg 29"

    # Second element should be from the tail (30 - 19 = 11)
    assert session.conversation_history[1].content == "msg 11"


def test_trim_history_exactly_at_limit():
    session = CallSession()
    for i in range(MAX_HISTORY):
        session.conversation_history.append(
            ConversationTurn(role="user", content=f"msg {i}")
        )
    session.trim_history()
    assert len(session.conversation_history) == MAX_HISTORY
    assert session.conversation_history[0].content == "msg 0"
    assert session.conversation_history[-1].content == f"msg {MAX_HISTORY - 1}"
