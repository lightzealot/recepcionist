# receptionist/known_callers.py
"""Known-caller directory: recognize companies by caller ID (ANI).

Operators maintain ``config/known_callers.json`` (next to the ``config/``
directory)::

    {"callers": [
        {"phone": "+17055551212", "company": "Acme Corp"},
        {"phone": "7055551313", "company": "Globex", "contact": "Jane",
         "business": "ITSpecialists"}
    ]}

``business`` is optional and scopes the entry to one tenant (matched
against ``config.business.name``, case-insensitive). Entries without it
apply to every tenant. ``contact`` is informational only.

Matching is digit-based: exact match after stripping non-digits, or
last-10-digits match when both sides have 10+ digits (so ``+1705…`` and
``705…`` forms of the same NANP number match). Numbers with fewer than
7 digits never match.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_DIRECTORY_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "known_callers.json"
)


@dataclass(frozen=True)
class KnownCaller:
    phone: str
    company: str
    contact: str = ""
    business: str = ""


def normalize_phone(phone: str | None) -> str:
    """Digits-only form of a phone number ("" when unusable)."""
    if not phone:
        return ""
    return re.sub(r"\D", "", phone)


def _digits_match(a: str, b: str) -> bool:
    if len(a) < 7 or len(b) < 7:
        return False
    if a == b:
        return True
    return len(a) >= 10 and len(b) >= 10 and a[-10:] == b[-10:]


@lru_cache(maxsize=1)
def load_known_callers(path: str | Path | None = None) -> list[KnownCaller]:
    """Load the directory. Missing/unreadable file (or bad JSON) -> []."""
    resolved = Path(path) if path else DEFAULT_DIRECTORY_PATH
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("callers", []) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    entries = []
    for item in items:
        if not isinstance(item, dict):
            continue
        phone = str(item.get("phone", "") or "")
        company = str(item.get("company", "") or "").strip()
        if not phone or not company:
            continue
        entries.append(KnownCaller(
            phone=phone,
            company=company,
            contact=str(item.get("contact", "") or ""),
            business=str(item.get("business", "") or ""),
        ))
    return entries


def lookup_known_caller(
    phone: str | None,
    business_name: str | None = None,
    entries: list[KnownCaller] | None = None,
) -> KnownCaller | None:
    """Return the directory entry matching `phone`, or None.

    Entries scoped to another business are skipped. Pass `entries`
    explicitly in tests to avoid touching the real directory file.
    """
    digits = normalize_phone(phone)
    if not digits:
        return None
    if entries is None:
        entries = load_known_callers()
    for entry in entries:
        if entry.business and business_name and \
                entry.business.strip().lower() != business_name.strip().lower():
            continue
        if _digits_match(digits, normalize_phone(entry.phone)):
            return entry
    return None
