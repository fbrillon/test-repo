"""Tests for user_profile.py — UserProfile dataclass and storage helpers."""

import json
from unittest.mock import patch


def test_userprofile_defaults():
    from user_profile import UserProfile

    p = UserProfile()
    assert p.schema_version == 1
    assert p.emails_analyzed == 0
    assert p.label_distribution == {}
    assert p.patterns == []


def test_userprofile_round_trip_json():
    from user_profile import UserProfile

    original = UserProfile(
        emails_analyzed=42,
        label_distribution={"Act_Now": 0.2, "Skip_It": 0.5},
        patterns=["newsletters are Skip_It", "direct questions are Act_Now"],
    )
    restored = UserProfile.from_json(original.to_json())
    assert restored.emails_analyzed == 42
    assert restored.label_distribution == {"Act_Now": 0.2, "Skip_It": 0.5}
    assert restored.patterns == original.patterns


def test_userprofile_from_json_ignores_unknown_fields():
    from user_profile import UserProfile

    raw = json.dumps({"emails_analyzed": 5, "unknown_field": "ignored"})
    p = UserProfile.from_json(raw)
    assert p.emails_analyzed == 5


def test_to_prompt_context_empty():
    from user_profile import UserProfile

    assert UserProfile().to_prompt_context() == ""


def test_to_prompt_context_populated():
    from user_profile import UserProfile

    p = UserProfile(
        emails_analyzed=10,
        label_distribution={"Act_Now": 0.3, "Skip_It": 0.7},
        patterns=["newsletters are Skip_It"],
    )
    ctx = p.to_prompt_context()
    assert "User Classification Profile" in ctx
    assert "10 historical emails" in ctx
    assert "Skip_It" in ctx
    assert "newsletters are Skip_It" in ctx


def test_load_profile_local_missing(tmp_path):
    with patch("user_profile._profile_path", return_value=tmp_path / "no.json"):
        from user_profile import _load_local

        assert _load_local("default") is None


def test_save_and_load_local(tmp_path):
    from user_profile import UserProfile, _load_local, _save_local

    with patch("user_profile._profile_path", return_value=tmp_path / "default.json"):
        p = UserProfile(emails_analyzed=7, patterns=["test pattern"])
        _save_local(p, "default")
        loaded = _load_local("default")

    assert loaded is not None
    assert loaded.emails_analyzed == 7
    assert loaded.patterns == ["test pattern"]
