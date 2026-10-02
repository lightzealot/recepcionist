# tests/test_known_callers.py
"""Known-caller directory: normalization, matching, tenant scoping."""
from __future__ import annotations

from receptionist.known_callers import (
    KnownCaller,
    lookup_known_caller,
    normalize_phone,
)

ENTRIES = [
    KnownCaller(phone="+17055551212", company="Acme Corp"),
    KnownCaller(phone="7055551313", company="Globex", business="ITSpecialists"),
    KnownCaller(phone="+15550001111", company="Other Shop", business="Someone Else"),
]


def test_normalize_strips_formatting():
    assert normalize_phone("+1 (705) 555-1212") == "17055551212"
    assert normalize_phone("705.555.1212") == "7055551212"
    assert normalize_phone(None) == ""
    assert normalize_phone("") == ""


def test_exact_match():
    hit = lookup_known_caller("+17055551212", "ITSpecialists", ENTRIES)
    assert hit is not None and hit.company == "Acme Corp"


def test_country_code_form_matches():
    # 11-digit 1+10 and plain 10-digit forms of the same NANP number match.
    hit = lookup_known_caller("7055551212", "ITSpecialists", ENTRIES)
    assert hit is not None and hit.company == "Acme Corp"
    hit = lookup_known_caller("+17055551313", "ITSpecialists", ENTRIES)
    assert hit is not None and hit.company == "Globex"


def test_unknown_number_returns_none():
    assert lookup_known_caller("+19995550000", "ITSpecialists", ENTRIES) is None
    assert lookup_known_caller(None, "ITSpecialists", ENTRIES) is None


def test_short_numbers_never_match():
    assert lookup_known_caller("1212", "ITSpecialists", ENTRIES) is None


def test_business_scoped_entries():
    # Scoped to this tenant -> matches.
    hit = lookup_known_caller("7055551313", "ITSpecialists", ENTRIES)
    assert hit is not None and hit.company == "Globex"
    # Scoped to another tenant -> ignored even with exact digits.
    assert lookup_known_caller("+15550001111", "ITSpecialists", ENTRIES) is None
    # Unscoped entries apply to every tenant.
    hit = lookup_known_caller("+17055551212", "Someone Else", ENTRIES)
    assert hit is not None and hit.company == "Acme Corp"


def test_missing_directory_file_matches_nothing(tmp_path, monkeypatch):
    from receptionist import known_callers

    monkeypatch.setattr(
        known_callers, "DEFAULT_DIRECTORY_PATH", tmp_path / "nope.json",
    )
    known_callers.load_known_callers.cache_clear()
    try:
        assert lookup_known_caller("+17055551212", "ITSpecialists") is None
    finally:
        known_callers.load_known_callers.cache_clear()
