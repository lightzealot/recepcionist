# tests/test_voice_preview.py
"""GET /api/voice-preview/{voice}: cached mp3, TTS generation, unavailable voices."""
from __future__ import annotations

from pathlib import Path

import respx
from fastapi.testclient import TestClient
from httpx import Response

import api_server


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setattr(api_server, "ROOT", tmp_path)
    monkeypatch.setattr(api_server, "TOKEN", "x")
    (tmp_path / "config" / "previews").mkdir(parents=True)
    return TestClient(api_server.app)


_H = {"Authorization": "Bearer x"}


def test_unknown_voice_400(monkeypatch, tmp_path) -> None:
    c = _client(monkeypatch, tmp_path)
    assert c.get("/api/voice-preview/mickey", headers=_H).status_code == 400


def test_realtime_only_voices_404(monkeypatch, tmp_path) -> None:
    c = _client(monkeypatch, tmp_path)
    for voice in ("marin", "verse"):
        r = c.get(f"/api/voice-preview/{voice}", headers=_H)
        assert r.status_code == 404


def test_cache_hit_serves_mp3(monkeypatch, tmp_path) -> None:
    c = _client(monkeypatch, tmp_path)
    blob = b"ID3_fake_mp3_bytes"
    (tmp_path / "config" / "previews" / "sage.mp3").write_bytes(blob)
    r = c.get("/api/voice-preview/sage", headers=_H)
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == blob


def test_requires_auth(monkeypatch, tmp_path) -> None:
    c = _client(monkeypatch, tmp_path)
    assert c.get("/api/voice-preview/sage").status_code in (401, 403)


@respx.mock
def test_cache_miss_generates_and_caches(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    route = respx.post("https://api.openai.com/v1/audio/speech").mock(
        return_value=Response(200, content=b"ID3_new_bytes"))
    c = _client(monkeypatch, tmp_path)
    r = c.get("/api/voice-preview/echo", headers=_H)
    assert r.status_code == 200
    assert r.content == b"ID3_new_bytes"
    assert (tmp_path / "config" / "previews" / "echo.mp3").read_bytes() == b"ID3_new_bytes"
    # Second call served from cache — no second TTS request.
    c.get("/api/voice-preview/echo", headers=_H)
    assert route.call_count == 1


@respx.mock
def test_tts_failure_is_502(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    respx.post("https://api.openai.com/v1/audio/speech").mock(
        return_value=Response(500))
    c = _client(monkeypatch, tmp_path)
    assert c.get("/api/voice-preview/coral", headers=_H).status_code == 502


def test_missing_api_key_is_500(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    c = _client(monkeypatch, tmp_path)
    assert c.get("/api/voice-preview/coral", headers=_H).status_code == 500
