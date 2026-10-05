# tests/transcript/test_backup.py
from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from receptionist.config import WebhookChannel as WebhookChannelConfig
from receptionist.transcript.backup import (
    build_backup_payload,
    post_transcript_backup,
)
from receptionist.transcript.capture import SpeakerRole, TranscriptSegment
from receptionist.transcript.metadata import CallMetadata


def _meta() -> CallMetadata:
    return CallMetadata(
        call_id="test-1", business_name="ITSpecialists",
        caller_phone="+17054810426",
    )


def _segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(role=SpeakerRole.USER, text="Hello", created_at=1790000000.0),
        TranscriptSegment(role=SpeakerRole.ASSISTANT, text="Hi there", created_at=1790000005.0),
    ]


def test_payload_shape() -> None:
    payload = build_backup_payload(_meta(), _segments())
    t = payload["transcript"]
    assert t["metadata"]["call_id"] == "test-1"
    assert t["metadata"]["caller_phone"] == "+17054810426"
    assert [s["role"] for s in t["segments"]] == ["user", "assistant"]
    assert t["segments"][0]["text"] == "Hello"
    assert t["segments"][1]["created_at"] == 1790000005.0
    json.dumps(payload)  # must be JSON-serializable


def test_payload_empty_segments() -> None:
    payload = build_backup_payload(_meta(), [])
    assert payload["transcript"]["segments"] == []
    assert payload["transcript"]["metadata"]["call_id"] == "test-1"


@pytest.mark.asyncio
@respx.mock
async def test_post_sends_payload_with_headers() -> None:
    route = respx.post("https://example.com/t").mock(return_value=Response(200))
    cfg = WebhookChannelConfig(
        type="webhook", url="https://example.com/t",
        headers={"Authorization": "Bearer s3cr3t"},
    )
    await post_transcript_backup(cfg, build_backup_payload(_meta(), _segments()))
    assert route.called
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer s3cr3t"
    assert json.loads(req.content)["transcript"]["metadata"]["call_id"] == "test-1"


@pytest.mark.asyncio
@respx.mock
async def test_post_4xx_does_not_retry() -> None:
    route = respx.post("https://example.com/t").mock(return_value=Response(400))
    cfg = WebhookChannelConfig(type="webhook", url="https://example.com/t", headers={})
    with pytest.raises(Exception):
        await post_transcript_backup(cfg, {"transcript": {}})
    assert route.call_count == 1
