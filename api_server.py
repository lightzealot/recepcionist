"""Dashboard sidecar API for AIReceptionist (read-only).

Serves calls, transcripts, messages, config summary, and a Twilio spend
snapshot to the static dashboard in dashboard/. Runs next to the worker:

    .venv/bin/python api_server.py

Env (.env):
    DASHBOARD_TOKEN         required bearer token for /api/*
    DASHBOARD_HOST          default 127.0.0.1
    DASHBOARD_PORT          default 8090
    DASHBOARD_CORS_ORIGINS  comma list, default *
    RECEPTIONIST_CONFIG     default business slug for /api/config
"""
from __future__ import annotations

import glob
import hmac
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from fastapi import Depends, FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # noqa: E402
from pydantic import BaseModel  # noqa: E402

ROOT = Path(__file__).parent
STARTED = time.time()

TOKEN = os.environ.get("DASHBOARD_TOKEN", "")
HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("DASHBOARD_PORT", "8090"))
CORS = [o.strip() for o in os.environ.get("DASHBOARD_CORS_ORIGINS", "*").split(",")]
SLUG = os.environ.get("RECEPTIONIST_CONFIG", "test-itspecialists")
# Same default as receptionist.agent.DEFAULT_AGENT_NAME (kept local so this
# sidecar doesn't import the heavy agent module).
AGENT_NAME = os.environ.get("RECEPTIONIST_AGENT_NAME", "receptionist")
LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "")

app = FastAPI(title="AIReceptionist dashboard API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
auth = HTTPBearer(auto_error=False)


def require_token(
    creds: HTTPAuthorizationCredentials | None = Depends(auth),
) -> None:
    if not TOKEN:
        raise HTTPException(500, "DASHBOARD_TOKEN not configured")
    if creds is None or not hmac.compare_digest(creds.credentials, TOKEN):
        raise HTTPException(401, "invalid token")


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _transcript_files() -> list[str]:
    files = glob.glob(str(ROOT / "transcripts" / "*" / "*.json"))
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files


def _message_files() -> list[str]:
    files = glob.glob(str(ROOT / "messages" / "*" / "message_*.json"))
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files


@app.get("/api/status", dependencies=[Depends(require_token)])
def status() -> dict:
    calls = _transcript_files()
    last_call = None
    if calls:
        data = _read_json(calls[0]) or {}
        last_call = (data.get("metadata") or {}).get("start_ts")
    return {
        "ok": True,
        "business_slug": SLUG,
        "uptime_seconds": int(time.time() - STARTED),
        "calls_recorded": len(calls),
        "messages_recorded": len(_message_files()),
        "last_call_at": last_call,
    }


@app.get("/api/calls", dependencies=[Depends(require_token)])
def list_calls(limit: int = 50) -> dict:
    items = []
    for path in _transcript_files()[:limit]:
        data = _read_json(path) or {}
        meta = data.get("metadata") or {}
        items.append({
            "call_id": meta.get("call_id") or Path(path).stem,
            "caller": meta.get("caller_phone"),
            "business": meta.get("business_name"),
            "start": meta.get("start_ts"),
            "end": meta.get("end_ts"),
            "duration_seconds": meta.get("duration_seconds"),
            "outcomes": meta.get("outcomes", []),
            "message_taken": meta.get("message_taken", False),
            "transfer_target": meta.get("transfer_target"),
        })
    return {"calls": items}


@app.get("/api/calls/{call_id:path}", dependencies=[Depends(require_token)])
def get_call(call_id: str) -> dict:
    for path in _transcript_files():
        data = _read_json(path) or {}
        meta = data.get("metadata") or {}
        if meta.get("call_id") == call_id or Path(path).stem == call_id:
            return {"metadata": meta, "segments": data.get("segments", [])}
    raise HTTPException(404, "call not found")


@app.get("/api/messages", dependencies=[Depends(require_token)])
def list_messages(limit: int = 50) -> dict:
    items = []
    for path in _message_files()[:limit]:
        data = _read_json(path)
        if data:
            items.append(data)
    return {"messages": items}


@app.get("/api/config", dependencies=[Depends(require_token)])
def config_summary() -> dict:
    from receptionist.config import load_config

    try:
        c = load_config(str(ROOT / "config" / "businesses" / f"{SLUG}.yaml"))
    except Exception as e:  # noqa: BLE001 - surface as 404 detail
        raise HTTPException(404, f"config '{SLUG}' not found: {e}")
    return {
        "slug": SLUG,
        "business": c.business.name,
        "type": c.business.type,
        "timezone": c.business.timezone,
        "model": c.voice.model,
        "voice": c.voice.voice_id,
        "languages": c.languages.allowed,
        "faqs": len(c.faqs),
        "transfers": len(c.routing),
        "greeting": c.greeting,
        "max_duration_min": (c.voice.idle.max_call_duration_seconds // 60
                             if c.voice.idle.max_call_duration_seconds else None),
    }


EDITABLE_VOICES = (
    "alloy", "ash", "ballad", "coral", "echo", "fable",
    "marin", "nova", "onyx", "sage", "shimmer", "verse",
)
CONFIG_PATCH_FIELDS = ("voice_id", "greeting", "max_duration_min")
_CONFIG_BACKUPS_KEPT = 3


def apply_config_patch(data: dict, patch: dict) -> dict:
    """Validate + apply a whitelisted config edit to parsed YAML. Pure.

    Raises ValueError on unknown fields, empty patch, or out-of-range
    values. Never mutates `data`.
    """
    import copy

    unknown = set(patch) - set(CONFIG_PATCH_FIELDS)
    if unknown:
        raise ValueError(f"fields not editable via dashboard: {sorted(unknown)}")
    if not patch:
        raise ValueError("empty patch")
    out = copy.deepcopy(data)
    if "voice_id" in patch:
        voice = patch["voice_id"]
        if voice not in EDITABLE_VOICES:
            raise ValueError(f"unknown voice_id: {voice!r}")
        out.setdefault("voice", {})["voice_id"] = voice
    if "greeting" in patch:
        greeting = patch["greeting"]
        if not isinstance(greeting, str) or not greeting.strip():
            raise ValueError("greeting must be non-empty text")
        if len(greeting) > 500:
            raise ValueError("greeting must be 500 chars or fewer")
        out["greeting"] = greeting.strip()
    if "max_duration_min" in patch:
        minutes = patch["max_duration_min"]
        if (isinstance(minutes, bool) or not isinstance(minutes, int)
                or not 1 <= minutes <= 30):
            raise ValueError("max_duration_min must be an integer 1-30")
        out.setdefault("voice", {}).setdefault("idle", {})[
            "max_call_duration_seconds"] = minutes * 60
    return out


def _business_config_path() -> Path:
    return ROOT / "config" / "businesses" / f"{SLUG}.yaml"


class ConfigPatchRequest(BaseModel):
    voice_id: str | None = None
    greeting: str | None = None
    max_duration_min: int | None = None


@app.patch("/api/config", dependencies=[Depends(require_token)])
def patch_config(req: ConfigPatchRequest) -> dict:
    """Edit voice/greeting/call-cap in the business YAML (whitelist only).

    Writes a timestamped .bak (keeps the last 3) and re-loads the file
    through the real config validator before returning. Applies to the
    next call — no restart needed. Requires /app/config on a Docker
    volume in production or a rebuild wipes the edit.
    """
    import shutil
    from datetime import datetime, timezone

    import yaml

    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    path = _business_config_path()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError:
        raise HTTPException(404, f"config '{SLUG}' not found")
    if not isinstance(data, dict):
        raise HTTPException(500, "config file is not a mapping")
    try:
        new_data = apply_config_patch(data, patch)
    except ValueError as e:
        raise HTTPException(400, str(e))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{stamp}")
    try:
        shutil.copy2(path, backup)
        for old in sorted(path.parent.glob(f"{path.name}.bak.*"))[: -_CONFIG_BACKUPS_KEPT]:
            old.unlink(missing_ok=True)
        path.write_text(
            yaml.safe_dump(new_data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    except OSError as e:
        raise HTTPException(500, f"config write failed: {e}")
    try:
        from receptionist.config import load_config

        updated = load_config(str(path))
    except Exception as e:  # noqa: BLE001 - validator detail is safe
        try:
            shutil.copy2(backup, path)  # restore last good on validation failure
        except OSError:
            pass
        raise HTTPException(500, f"edited config failed validation: {e}")
    idle = updated.voice.idle
    return {
        "updated": sorted(patch),
        "updated_at": stamp,
        "backup": backup.name,
        "values": {
            "voice_id": updated.voice.voice_id,
            "greeting": updated.greeting,
            "max_duration_min": (idle.max_call_duration_seconds // 60
                                 if idle.max_call_duration_seconds else None),
        },
        "note": "Applies to the next call — no restart needed.",
    }


# marin/verse are Realtime-only voices with no TTS equivalent to sample.
PREVIEWABLE_VOICES = tuple(v for v in EDITABLE_VOICES if v not in ("marin", "verse"))
PREVIEW_TEXT = "Hello! This is a preview of my voice for ITSpecialists."
PREVIEW_MODEL = "gpt-4o-mini-tts"


def _previews_dir() -> Path:
    return ROOT / "config" / "previews"


async def _synthesize_preview(voice: str, api_key: str) -> bytes:
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": PREVIEW_MODEL, "input": PREVIEW_TEXT, "voice": voice},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"TTS HTTP {resp.status_code}")
    return resp.content


@app.get("/api/voice-preview/{voice}", dependencies=[Depends(require_token)])
async def voice_preview(voice: str):
    """Sample mp3 for a voice, generated once via cheap TTS then cached.

    Cached under the config volume so previews survive rebuilds.
    Realtime-only voices (marin, verse) have no TTS equivalent: 404.
    """
    from fastapi.responses import FileResponse

    if voice not in EDITABLE_VOICES:
        raise HTTPException(400, f"unknown voice: {voice!r}")
    if voice not in PREVIEWABLE_VOICES:
        raise HTTPException(
            404, f"no preview for {voice} (Realtime-only voice) — use a test call")
    path = _previews_dir() / f"{voice}.mp3"
    if not path.exists():
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise HTTPException(500, "OPENAI_API_KEY not configured")
        try:
            data = await _synthesize_preview(voice, api_key)
        except Exception as e:  # noqa: BLE001 - no secrets in type name
            raise HTTPException(502, f"preview synthesis failed: {type(e).__name__}")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError as e:
            raise HTTPException(500, f"preview cache write failed: {e}")
    return FileResponse(path, media_type="audio/mpeg", filename=f"{voice}.mp3")


@app.get("/api/known-callers", dependencies=[Depends(require_token)])
def known_callers() -> dict:
    from receptionist.known_callers import load_known_callers

    return {
        "callers": [
            {"phone": c.phone, "company": c.company, "contact": c.contact}
            for c in load_known_callers()
        ],
    }


class TestCallRequest(BaseModel):
    caller_phone: str = ""
    caller_name: str = "Test caller"
    dry_run: bool = False


@app.post("/api/test-call", dependencies=[Depends(require_token)])
async def test_call(req: TestCallRequest) -> dict:
    """Spin up a dashboard test room with the agent dispatched into it.

    Returns a browser join URL (open it on a phone: the Mac mini has no
    mic). `caller_phone` simulates that caller ID so the known-caller
    greeting can be verified without the real phones. `dry_run` validates
    everything without dispatching (costs $0; a real dispatch runs the
    voice model at ~$0.03/min once the agent joins).
    """
    import re
    from datetime import timedelta
    from urllib.parse import quote

    phone = req.caller_phone.strip()
    if phone and not re.fullmatch(r"\+?[0-9][0-9 .()/-]{5,25}", phone):
        raise HTTPException(400, "invalid caller_phone")
    if not LIVEKIT_URL:
        raise HTTPException(500, "LIVEKIT_URL not configured")
    room = f"test-{int(time.time())}"
    if req.dry_run:
        return {"room": room, "dry_run": True, "agent": AGENT_NAME,
                "caller_phone": phone or None}

    from livekit import api as lkapi

    metadata = json.dumps({"config": SLUG, "test_caller_phone": phone})
    client = lkapi.LiveKitAPI()
    try:
        await client.agent_dispatch.create_dispatch(
            lkapi.CreateAgentDispatchRequest(
                room=room, agent_name=AGENT_NAME, metadata=metadata,
            )
        )
    except Exception as e:  # noqa: BLE001 - surface dispatch errors as 502
        raise HTTPException(502, f"dispatch failed: {type(e).__name__}: {e}")
    finally:
        await client.aclose()

    key = os.environ.get("LIVEKIT_API_KEY", "")
    secret = os.environ.get("LIVEKIT_API_SECRET", "")
    if not key or not secret:
        raise HTTPException(500, "LIVEKIT_API_KEY/SECRET not configured")
    token = (
        lkapi.AccessToken(key, secret)
        .with_identity("test-caller")
        .with_name(req.caller_name.strip() or "Test caller")
        .with_grants(lkapi.VideoGrants(room_join=True, room=room))
        .with_ttl(timedelta(minutes=15))
        .to_jwt()
    )
    url = (f"https://meet.livekit.io/custom?liveKitUrl={quote(LIVEKIT_URL)}"
           f"&token={quote(token)}")
    return {"room": room, "url": url, "token": token,
            "caller_phone": phone or None}


@app.get("/api/spend", dependencies=[Depends(require_token)])
def spend() -> dict:
    try:
        from twilio.rest import Client
    except ImportError:
        return {"error": "twilio lib not installed"}
    try:
        client = Client()
        bal = client.api.v2010.account.balance.fetch()
        cats = []
        for r in client.usage.records.monthly.list():
            try:
                price = float(r.price or 0)
            except (TypeError, ValueError):
                price = 0.0
            if price == 0 and (not r.usage or r.usage == "0"):
                continue
            if (r.category or "").lower().startswith("total"):
                continue  # aggregate row, not additive
            cats.append({
                "category": r.category,
                "used": r.usage,
                "unit": r.usage_unit,
                "price": price,
            })
        return {
            "balance": float(bal.balance),
            "currency": bal.currency,
            "month_categories": cats[:10],
        }
    except Exception as e:  # noqa: BLE001 - no secrets in type name
        return {"error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    import uvicorn

    if not TOKEN:
        raise SystemExit("Set DASHBOARD_TOKEN in .env first")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
