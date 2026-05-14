#!/usr/bin/env python3
"""
Profiler: builds and refreshes the user's classification profile from Gmail history.

Extracts PII-free structural signals from recent threads and uses Claude to
identify behavioral classification patterns. Run periodically to keep the
profile current as email habits evolve. No names, addresses, subjects, or
message content are sent to the Claude API — only anonymized structural signals.

Usage:
    python profiler.py
    python profiler.py --user alice --sample-size 150
"""

import argparse
import json
import os
import re
import sys

import anthropic
from dotenv import load_dotenv

from gmail_auth import get_gmail_service, set_user
from user_profile import PROFILE_EXTRACTION_PROMPT, UserProfile, save_profile

load_dotenv()

TRIAGE_LABEL_NAMES = ["Act_Now", "Next_Moves", "Track_It", "Stay_Informed", "Skip_It"]
DEFAULT_SAMPLE_SIZE = 100


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _sender_type(headers: list[dict]) -> str:
    """Classify sender without retaining any identifying values."""
    from_val = _get_header(headers, "From").lower()
    if _get_header(headers, "List-Unsubscribe"):
        return "newsletter"
    if _get_header(headers, "List-Id"):
        return "mailing_list"
    if re.search(r"\bno.?reply\b", from_val):
        return "no_reply"
    if re.search(r"(notification|alert|update|noreply|donotreply|daemon)s?@", from_val):
        return "automated"
    return "personal"


def _subject_flags(subject: str) -> list[str]:
    """Return structural flags for a subject without retaining the text."""
    flags = []
    s = subject.lower()
    if re.match(r"re\s*:", s):
        flags.append("is_reply")
    if re.match(r"fwd?\s*:", s):
        flags.append("is_forward")
    if "?" in subject:
        flags.append("has_question")
    if re.search(r"\b(invoice|receipt|order|confirmation|booking|ticket)\b", s):
        flags.append("transactional")
    if re.search(r"\b(urgent|asap|action required|reminder)\b", s):
        flags.append("urgency_signal")
    if re.search(r"\b(unsubscribe|newsletter|digest|weekly|monthly)\b", s):
        flags.append("newsletter_signal")
    if re.search(r"(\$|€|£|\bpayment\b|\bprice\b|\bcost\b)", s):
        flags.append("financial_signal")
    return flags


def extract_thread_signals(thread: dict, triage_id_to_name: dict[str, str]) -> dict | None:
    """Return PII-free structural signals for one thread, or None if empty."""
    messages = thread.get("messages", [])
    if not messages:
        return None

    first_msg = messages[0]
    first_headers = first_msg.get("payload", {}).get("headers", [])

    senders: set[str] = set()
    has_user_reply = False
    all_label_ids: set[str] = set()
    for msg in messages:
        msg_headers = msg.get("payload", {}).get("headers", [])
        senders.add(_get_header(msg_headers, "From"))
        if "SENT" in msg.get("labelIds", []):
            has_user_reply = True
        all_label_ids.update(msg.get("labelIds", []))

    try:
        first_ts = int(first_msg.get("internalDate", 0))
        last_ts = int(messages[-1].get("internalDate", 0))
        duration_hours = round((last_ts - first_ts) / 3_600_000, 1)
    except (ValueError, TypeError):
        duration_hours = 0.0

    has_attachment = any(
        part.get("filename")
        for msg in messages
        for part in msg.get("payload", {}).get("parts", [])
    )

    to_val = _get_header(first_headers, "To")
    cc_val = _get_header(first_headers, "Cc")
    recipient_count = len([x for x in to_val.split(",") if x.strip()]) + (
        len([x for x in cc_val.split(",") if x.strip()]) if cc_val else 0
    )

    triage_label = next(
        (triage_id_to_name[lid] for lid in all_label_ids if lid in triage_id_to_name), None
    )

    return {
        "thread_length": len(messages),
        "participant_count": len(senders),
        "sender_type": _sender_type(first_headers),
        "subject_flags": _subject_flags(_get_header(first_headers, "Subject")),
        "has_user_reply": has_user_reply,
        "duration_hours": duration_hours,
        "has_attachment": has_attachment,
        "recipient_count": min(recipient_count, 20),
        "triage_label": triage_label,
    }


def fetch_thread_signals(
    service, sample_size: int, label_map: dict[str, str]
) -> list[dict]:
    """Fetch recent threads and return a list of anonymized structural signals."""
    triage_id_to_name = {v: k for k, v in label_map.items()}
    signals: list[dict] = []
    page_token = None

    print(f"Fetching up to {sample_size} historical threads…")
    while len(signals) < sample_size:
        params: dict = {
            "userId": "me",
            "q": "in:inbox OR in:sent",
            "maxResults": min(50, sample_size - len(signals)),
        }
        if page_token:
            params["pageToken"] = page_token

        response = service.threads().list(**params).execute()
        raw = response.get("threads", [])
        if not raw:
            break

        for t in raw:
            thread = service.threads().get(
                userId="me",
                id=t["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "To", "Cc", "List-Unsubscribe", "List-Id", "Reply-To"],
            ).execute()
            sig = extract_thread_signals(thread, triage_id_to_name)
            if sig:
                signals.append(sig)
            if len(signals) >= sample_size:
                break

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    print(f"Collected signals for {len(signals)} threads.")
    return signals


def signals_to_text(signals: list[dict]) -> str:
    """Format thread signals as plain text for Claude's context window."""
    lines = []
    for i, s in enumerate(signals, 1):
        parts = [
            f"length={s['thread_length']}",
            f"participants={s['participant_count']}",
            f"sender={s['sender_type']}",
            f"replied={s['has_user_reply']}",
            f"duration_h={s['duration_hours']}",
            f"attachment={s['has_attachment']}",
            f"recipients={s['recipient_count']}",
        ]
        if s["subject_flags"]:
            parts.append(f"subject=[{','.join(s['subject_flags'])}]")
        if s["triage_label"]:
            parts.append(f"label={s['triage_label']}")
        lines.append(f"T{i}: " + " | ".join(parts))
    return "\n".join(lines)


def build_profile(service, sample_size: int = DEFAULT_SAMPLE_SIZE) -> UserProfile:
    """
    Build a UserProfile from historical Gmail threads.
    Only anonymized behavioral patterns are extracted — no PII.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    labels_response = service.users().labels().list(userId="me").execute()
    label_map = {
        lbl["name"]: lbl["id"]
        for lbl in labels_response.get("labels", [])
        if lbl["name"] in TRIAGE_LABEL_NAMES
    }

    signals = fetch_thread_signals(service, sample_size, label_map)
    if not signals:
        print("No threads found. Returning empty profile.")
        return UserProfile()

    user_message = (
        f"Here are anonymized structural signals for {len(signals)} recent email threads:\n\n"
        + signals_to_text(signals)
    )

    print("Analyzing patterns with Claude…")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=PROFILE_EXTRACTION_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_json = response.content[0].text.strip()
    raw_json = re.sub(r"^```(?:json)?\s*", "", raw_json)
    raw_json = re.sub(r"\s*```$", "", raw_json)

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        print(f"WARNING: Claude returned invalid JSON: {exc}")
        print("Raw response:", raw_json[:500])
        return UserProfile(emails_analyzed=len(signals))

    return UserProfile(
        emails_analyzed=data.get("emails_analyzed", len(signals)),
        label_distribution=data.get("label_distribution", {}),
        patterns=data.get("patterns", []),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build initial user profile from Gmail history")
    parser.add_argument("--user", default=None, help="User ID for multi-user setups")
    parser.add_argument(
        "--sample-size",
        type=int,
        default=DEFAULT_SAMPLE_SIZE,
        help=f"Number of historical threads to analyze (default: {DEFAULT_SAMPLE_SIZE})",
    )
    args = parser.parse_args()

    if args.user:
        set_user(args.user)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ERROR: ANTHROPIC_API_KEY environment variable is not set.")

    service = get_gmail_service()
    profile = build_profile(service, sample_size=args.sample_size)

    save_profile(profile, user_id=args.user or "")
    print(f"\nProfile saved. Analyzed {profile.emails_analyzed} threads.")
    if profile.label_distribution:
        print("Label distribution:")
        for label, pct in sorted(profile.label_distribution.items(), key=lambda x: -x[1]):
            print(f"  {label}: {pct:.0%}")
    if profile.patterns:
        print(f"Patterns ({len(profile.patterns)}):")
        for p in profile.patterns:
            print(f"  - {p}")


if __name__ == "__main__":
    main()
