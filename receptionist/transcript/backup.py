# receptionist/transcript/backup.py
"""POST the finalized call transcript to a backup webhook (n8n -> Sheets).

Configured via `transcripts.backup_webhook` (same url/headers shape as a
message webhook channel). Fired once from `CallLifecycle.on_call_ended`
after the local transcript files are written. Failures are logged by the
caller and never break call finalization.
"""
from __future__ import annotations

import logging
from typing import Sequence
from urllib.parse import urlsplit, urlunsplit

import httpx

from receptionist.config import WebhookChannel as WebhookChannelConfig
from receptionist.messaging.retry import retry_with_backoff, RetryPolicy
from receptionist.transcript.capture import TranscriptSegment
from receptionist.transcript.metadata import CallMetadata

logger = logging.getLogger("receptionist")


def build_backup_payload(
    metadata: CallMetadata, segments: Sequence[TranscriptSegment],
) -> dict:
    return {
        "transcript": {
            "metadata": metadata.to_dict(),
            "segments": [
                {
                    "role": s.role.value,
                    "text": s.text,
                    "created_at": s.created_at,
                    "language": s.language,
                }
                for s in segments
            ],
        },
    }


class _PermanentHTTPError(Exception):
    """4xx response — no retry."""


async def post_transcript_backup(
    config: WebhookChannelConfig,
    payload: dict,
    initial_delay: float = 1.0,
) -> None:
    """POST `payload` to the backup URL with retry on 5xx/timeout."""
    policy = RetryPolicy(max_attempts=3, initial_delay=initial_delay, factor=2.0)
    redacted = urlunsplit((urlsplit(config.url).scheme, urlsplit(config.url).netloc,
                           urlsplit(config.url).path, "", ""))

    async def _post() -> None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(config.url, json=payload, headers=config.headers)
        if 400 <= resp.status_code < 500:
            raise _PermanentHTTPError(f"HTTP {resp.status_code} from {redacted}")
        resp.raise_for_status()
        logger.info("TranscriptBackup POST %s -> %d", redacted, resp.status_code)

    await retry_with_backoff(
        _post,
        policy,
        is_transient=lambda e: not isinstance(e, _PermanentHTTPError),
    )
