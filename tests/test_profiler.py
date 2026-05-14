"""Tests for profiler.py — signal extraction helpers."""


def test_sender_type_newsletter():
    from profiler import _sender_type

    headers = [{"name": "From", "value": "news@example.com"}, {"name": "List-Unsubscribe", "value": "<mailto:unsub@example.com>"}]
    assert _sender_type(headers) == "newsletter"


def test_sender_type_mailing_list():
    from profiler import _sender_type

    headers = [{"name": "From", "value": "list@example.com"}, {"name": "List-Id", "value": "<mylist.example.com>"}]
    assert _sender_type(headers) == "mailing_list"


def test_sender_type_no_reply():
    from profiler import _sender_type

    headers = [{"name": "From", "value": "no-reply@service.com"}]
    assert _sender_type(headers) == "no_reply"


def test_sender_type_automated():
    from profiler import _sender_type

    headers = [{"name": "From", "value": "notifications@service.com"}]
    assert _sender_type(headers) == "automated"


def test_sender_type_personal():
    from profiler import _sender_type

    headers = [{"name": "From", "value": "Alice Smith <alice@personal.com>"}]
    assert _sender_type(headers) == "personal"


def test_subject_flags_reply():
    from profiler import _subject_flags

    assert "is_reply" in _subject_flags("Re: your question")


def test_subject_flags_transactional():
    from profiler import _subject_flags

    assert "transactional" in _subject_flags("Your invoice is ready")


def test_subject_flags_urgency():
    from profiler import _subject_flags

    assert "urgency_signal" in _subject_flags("URGENT: action required")


def test_subject_flags_empty():
    from profiler import _subject_flags

    assert _subject_flags("Hello there") == []


def test_extract_thread_signals_empty():
    from profiler import extract_thread_signals

    assert extract_thread_signals({"messages": []}, {}) is None


def test_extract_thread_signals_basic():
    from profiler import extract_thread_signals

    thread = {
        "messages": [
            {
                "internalDate": "1000000",
                "labelIds": ["INBOX"],
                "payload": {
                    "headers": [
                        {"name": "From", "value": "alice@example.com"},
                        {"name": "To", "value": "bob@example.com"},
                        {"name": "Subject", "value": "Hello"},
                    ],
                    "parts": [],
                },
            }
        ]
    }
    sig = extract_thread_signals(thread, {})
    assert sig is not None
    assert sig["thread_length"] == 1
    assert sig["sender_type"] == "personal"
    assert sig["has_user_reply"] is False
    assert sig["triage_label"] is None


def test_extract_thread_signals_triage_label():
    from profiler import extract_thread_signals

    triage_map = {"label_act_now_id": "Act_Now"}
    thread = {
        "messages": [
            {
                "internalDate": "1000000",
                "labelIds": ["INBOX", "label_act_now_id"],
                "payload": {
                    "headers": [{"name": "From", "value": "someone@example.com"}],
                    "parts": [],
                },
            }
        ]
    }
    sig = extract_thread_signals(thread, triage_map)
    assert sig["triage_label"] == "Act_Now"


def test_signals_to_text():
    from profiler import signals_to_text

    signals = [
        {
            "thread_length": 2,
            "participant_count": 2,
            "sender_type": "personal",
            "subject_flags": ["has_question"],
            "has_user_reply": True,
            "duration_hours": 1.5,
            "has_attachment": False,
            "recipient_count": 1,
            "triage_label": "Act_Now",
        }
    ]
    text = signals_to_text(signals)
    assert "T1:" in text
    assert "sender=personal" in text
    assert "has_question" in text
    assert "label=Act_Now" in text
