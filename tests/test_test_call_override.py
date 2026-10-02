# tests/test_test_call_override.py
"""Dashboard test rooms can simulate a caller ID (ANI override).

The override is honored ONLY in rooms named `test-*` so a stray
`test_caller_phone` in real-call metadata can never spoof caller ID.
"""
from types import SimpleNamespace

import pytest

from receptionist.agent import _get_test_caller_override


def _ctx(*, room: str, metadata: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        room=SimpleNamespace(name=room),
        job=SimpleNamespace(metadata=metadata),
    )


def test_override_honored_in_test_room() -> None:
    ctx = _ctx(room="test-1234", metadata='{"test_caller_phone": "7054810426"}')
    assert _get_test_caller_override(ctx) == "7054810426"


def test_override_ignored_in_real_room() -> None:
    ctx = _ctx(room="sip-abc123", metadata='{"test_caller_phone": "7054810426"}')
    assert _get_test_caller_override(ctx) is None


def test_override_ignored_without_metadata() -> None:
    assert _get_test_caller_override(_ctx(room="test-1", metadata=None)) is None
    assert _get_test_caller_override(_ctx(room="test-1", metadata="")) is None
    assert _get_test_caller_override(_ctx(room="test-1", metadata="{}")) is None


def test_override_ignored_with_bad_metadata() -> None:
    assert _get_test_caller_override(_ctx(room="test-1", metadata="nope")) is None
    assert _get_test_caller_override(_ctx(room="test-1", metadata="[]")) is None
    ctx = _ctx(room="test-1", metadata='{"test_caller_phone": "   "}')
    assert _get_test_caller_override(ctx) is None


def test_override_strips_whitespace() -> None:
    ctx = _ctx(room="test-1", metadata='{"test_caller_phone": "  +17054810426 "}')
    assert _get_test_caller_override(ctx) == "+17054810426"


@pytest.mark.parametrize("room", ["Test-1", "latest-call", "contest-room"])
def test_override_requires_lowercase_test_prefix(room: str) -> None:
    ctx = _ctx(room=room, metadata='{"test_caller_phone": "7054810426"}')
    assert _get_test_caller_override(ctx) is None
