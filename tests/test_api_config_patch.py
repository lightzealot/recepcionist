# tests/test_api_config_patch.py
"""PATCH /api/config validation: whitelist, ranges, no unrelated mutation."""
import copy

import pytest

from api_server import EDITABLE_VOICES, apply_config_patch


def _data() -> dict:
    return {
        "business": {"name": "ITSpecialists"},
        "voice": {"voice_id": "marin", "idle": {"max_call_duration_seconds": 300}},
        "greeting": "Hello.",
        "faqs": [],
    }


def test_voice_ok() -> None:
    out = apply_config_patch(_data(), {"voice_id": "sage"})
    assert out["voice"]["voice_id"] == "sage"


def test_voice_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        apply_config_patch(_data(), {"voice_id": "mickey-mouse"})


def test_voice_list_sane() -> None:
    assert "marin" in EDITABLE_VOICES  # current production voice stays legal
    assert len(EDITABLE_VOICES) >= 6


def test_greeting_ok_and_trimmed() -> None:
    out = apply_config_patch(_data(), {"greeting": "  Hi.  "})
    assert out["greeting"] == "Hi."


@pytest.mark.parametrize("bad", ["", "   ", "x" * 501, 123, None])
def test_greeting_rejects_bad(bad) -> None:
    with pytest.raises(ValueError):
        apply_config_patch(_data(), {"greeting": bad})


def test_duration_ok_converts_to_seconds() -> None:
    out = apply_config_patch(_data(), {"max_duration_min": 10})
    assert out["voice"]["idle"]["max_call_duration_seconds"] == 600


@pytest.mark.parametrize("bad", [0, -3, 31, True, "10", 2.5, None])
def test_duration_rejects_bad(bad) -> None:
    with pytest.raises(ValueError):
        apply_config_patch(_data(), {"max_duration_min": bad})


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValueError):
        apply_config_patch(_data(), {"model": "gpt-realtime-2.1"})


def test_empty_patch_rejected() -> None:
    with pytest.raises(ValueError):
        apply_config_patch(_data(), {})


def test_does_not_mutate_input_or_other_keys() -> None:
    data = _data()
    before = copy.deepcopy(data)
    out = apply_config_patch(data, {"voice_id": "echo", "max_duration_min": 3})
    assert data == before
    assert out["business"] == before["business"]
    assert out["faqs"] == before["faqs"]
    assert out["voice"]["idle"]["max_call_duration_seconds"] == 180
