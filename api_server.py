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
    }


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
