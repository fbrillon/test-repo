import base64
import os

import pytest

# ---------------------------------------------------------------------------
# gmail_auth — set_user validation
# ---------------------------------------------------------------------------

def test_set_user_valid(monkeypatch):
    from gmail_auth import set_user
    set_user("alice")
    assert os.environ["SECRET_PREFIX"] == "gmail-agent/alice"


def test_set_user_hyphens_and_underscores(monkeypatch):
    from gmail_auth import set_user
    set_user("alice-bob_42")
    assert os.environ["SECRET_PREFIX"] == "gmail-agent/alice-bob_42"


def test_set_user_rejects_slash():
    from gmail_auth import set_user
    with pytest.raises(ValueError):
        set_user("alice/../../admin")


def test_set_user_rejects_empty():
    from gmail_auth import set_user
    with pytest.raises(ValueError):
        set_user("")


def test_set_user_rejects_special_chars():
    from gmail_auth import set_user
    with pytest.raises(ValueError):
        set_user("alice@example.com")


def test_set_user_rejects_too_long():
    from gmail_auth import set_user
    with pytest.raises(ValueError):
        set_user("a" * 65)


# ---------------------------------------------------------------------------
# agent — pure helper functions
# ---------------------------------------------------------------------------

def test_header_found():
    from agent import _header
    headers = [{"name": "Subject", "value": "Hello"}, {"name": "From", "value": "a@b.com"}]
    assert _header(headers, "Subject") == "Hello"


def test_header_case_insensitive():
    from agent import _header
    headers = [{"name": "SUBJECT", "value": "Hello"}]
    assert _header(headers, "subject") == "Hello"


def test_header_missing():
    from agent import _header
    assert _header([], "Subject") == ""


def test_decode_body_plain():
    from agent import _decode_body
    text = "Hello, world!"
    encoded = base64.urlsafe_b64encode(text.encode()).decode()
    assert _decode_body({"body": {"data": encoded}}) == text


def test_decode_body_strips_html():
    from agent import _decode_body
    html = "<p>Hello <b>world</b></p>"
    encoded = base64.urlsafe_b64encode(html.encode()).decode()
    result = _decode_body({"body": {"data": encoded}})
    assert "<" not in result
    assert "Hello" in result


def test_decode_body_empty():
    from agent import _decode_body
    assert _decode_body({"body": {}}) == ""


def test_extract_text_plain():
    from agent import _extract_text
    text = "Hello"
    encoded = base64.urlsafe_b64encode(text.encode()).decode()
    payload = {"mimeType": "text/plain", "body": {"data": encoded}}
    assert _extract_text(payload) == text


def test_extract_text_nested():
    from agent import _extract_text
    text = "Nested body"
    encoded = base64.urlsafe_b64encode(text.encode()).decode()
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [{"mimeType": "text/plain", "body": {"data": encoded}}],
    }
    assert _extract_text(payload) == text


def test_extract_text_missing():
    from agent import _extract_text
    assert _extract_text({"mimeType": "text/html", "body": {}}, "text/plain") == ""


# ---------------------------------------------------------------------------
# agent — resolve_label_ids creates missing labels
# ---------------------------------------------------------------------------

def test_resolve_label_ids_existing():
    from unittest.mock import MagicMock

    from agent import resolve_label_ids

    svc = MagicMock()
    svc.users().labels().list().execute.return_value = {
        "labels": [
            {"name": "Act_Now",       "id": "L1"},
            {"name": "Next_Moves",    "id": "L2"},
            {"name": "Track_It",      "id": "L3"},
            {"name": "Stay_Informed", "id": "L4"},
            {"name": "Skip_It",       "id": "L5"},
        ]
    }
    result = resolve_label_ids(svc)
    assert result == {
        "Act_Now": "L1", "Next_Moves": "L2", "Track_It": "L3",
        "Stay_Informed": "L4", "Skip_It": "L5",
    }


def test_resolve_label_ids_creates_missing():
    from unittest.mock import MagicMock

    from agent import TRIAGE_LABEL_NAMES, resolve_label_ids

    svc = MagicMock()
    svc.users().labels().list().execute.return_value = {"labels": []}
    svc.users().labels().create().execute.return_value = {"id": "L_new"}

    result = resolve_label_ids(svc)
    assert set(result.keys()) == set(TRIAGE_LABEL_NAMES)
