#!/usr/bin/env python3
"""
Gmail Email Labeling Agent

Reads unread Gmail threads and applies triage labels using Claude's reasoning.
"""

import argparse
import base64
import json
import os
import re
import sys
from typing import Any

import anthropic
from dotenv import load_dotenv

from gmail_auth import get_gmail_service, set_user, upload_token_to_secrets_manager

load_dotenv()

TRIAGE_LABEL_NAMES = ["Act_Now", "Next_Moves", "Track_It", "Stay_Informed", "Skip_It"]

SYSTEM_PROMPT = """\
You are an email triage assistant. Your job is to classify unread Gmail threads
and apply exactly one triage label to each, based on content and urgency.

Label definitions:
- Act_Now:      Requires a reply or concrete action today. Someone is waiting on you.
- Next_Moves:   Requires action but not urgent. Can be handled in the next few days.
- Track_It:     Receipt, order confirmation, or thread where you are waiting on a reply. Monitor only.
- Stay_Informed: Informational — worth reading but no action required.
- Skip_It:      Newsletter, promotion, automated notification, or anything not worth reading.

Your process:
1. Call search_unread_threads to get a page of unread threads.
2. For each thread_id returned, call get_thread to read its content.
3. Classify the thread and call apply_label with your chosen label and a brief reason.
4. If search_unread_threads returned a next_page_token, call it again with that token to get more threads.
5. Repeat until all unread threads have been labeled.

Rules:
- Every thread gets exactly one label. Do not skip any thread.
- Threads that already have a triage label are pre-filtered and won't appear in results.
- Be decisive. A brief glance at subject + sender + snippet is often enough to classify.
"""

def resolve_label_ids(service) -> dict[str, str]:
    """Map triage label names to Gmail IDs, creating any that don't exist yet."""
    response = service.users().labels().list(userId="me").execute()
    existing = {l["name"]: l["id"] for l in response.get("labels", [])}
    result = {}
    for name in TRIAGE_LABEL_NAMES:
        if name in existing:
            result[name] = existing[name]
        else:
            created = service.users().labels().create(
                userId="me",
                body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
            ).execute()
            result[name] = created["id"]
            print(f"Created label: {name} ({created['id']})")
    return result


TOOLS = [
    {
        "name": "search_unread_threads",
        "description": (
            "Fetch a page of unread Gmail threads that don't yet have a triage label. "
            "Returns a list of {thread_id, subject, sender, snippet} and an optional next_page_token."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "page_token": {
                    "type": "string",
                    "description": "Pagination token from a previous call. Omit to start from the first page.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_thread",
        "description": "Fetch the full content of a Gmail thread by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "The Gmail thread ID.",
                },
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "apply_label",
        "description": "Apply a triage label to a Gmail thread.",
        "input_schema": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "The Gmail thread ID."},
                "label": {
                    "type": "string",
                    "enum": TRIAGE_LABEL_NAMES,
                    "description": "The triage label to apply.",
                },
                "reason": {
                    "type": "string",
                    "description": "One sentence explaining the classification.",
                },
            },
            "required": ["thread_id", "label", "reason"],
        },
    },
]


# ---------------------------------------------------------------------------
# Gmail helpers
# ---------------------------------------------------------------------------


def _decode_body(part: dict) -> str:
    data = part.get("body", {}).get("data", "")
    if not data:
        return ""
    text = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    # Strip HTML tags for readability
    return re.sub(r"<[^>]+>", " ", text).strip()


def _extract_text(payload: dict, mime_type: str = "text/plain") -> str:
    if payload.get("mimeType") == mime_type:
        return _decode_body(payload)
    for part in payload.get("parts", []):
        result = _extract_text(part, mime_type)
        if result:
            return result
    return ""


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def search_unread_threads(
    service, max_results: int, triage_label_ids: set[str], page_token: str | None = None
) -> dict:
    params: dict[str, Any] = {
        "userId": "me",
        "q": "is:unread -in:draft",
        "maxResults": min(max_results, 50),
    }
    if page_token:
        params["pageToken"] = page_token

    response = service.threads().list(**params).execute()
    raw_threads = response.get("threads", [])
    next_token = response.get("nextPageToken")

    threads = []
    for t in raw_threads:
        meta = (
            service.threads()
            .get(userId="me", id=t["id"], format="metadata", metadataHeaders=["Subject", "From"])
            .execute()
        )
        first_msg = meta["messages"][0]
        headers = first_msg.get("payload", {}).get("headers", [])
        label_ids = set(first_msg.get("labelIds", []))

        if label_ids & triage_label_ids:
            continue

        threads.append(
            {
                "thread_id": t["id"],
                "subject": _header(headers, "Subject") or "(no subject)",
                "sender": _header(headers, "From"),
                "snippet": meta["messages"][-1].get("snippet", ""),
            }
        )

    return {"threads": threads, "next_page_token": next_token}


def get_thread(service, thread_id: str) -> dict:
    thread = service.threads().get(userId="me", id=thread_id, format="full").execute()
    messages = []
    for msg in thread.get("messages", [])[-3:]:  # last 3 messages are enough
        headers = msg.get("payload", {}).get("headers", [])
        body = _extract_text(msg.get("payload", {}), "text/plain")
        if not body:
            body = _extract_text(msg.get("payload", {}), "text/html")
        messages.append(
            {
                "from": _header(headers, "From"),
                "to": _header(headers, "To"),
                "date": _header(headers, "Date"),
                "subject": _header(headers, "Subject"),
                "body": body[:2000],  # cap at 2000 chars per message
            }
        )
    return {"thread_id": thread_id, "message_count": len(thread["messages"]), "messages": messages}


def apply_label(service, thread_id: str, label_name: str, label_map: dict[str, str], dry_run: bool) -> dict:
    label_id = label_map[label_name]
    if not dry_run:
        service.threads().modify(
            userId="me",
            id=thread_id,
            body={"addLabelIds": [label_id]},
        ).execute()
    return {"status": "ok" if not dry_run else "dry-run", "thread_id": thread_id, "label": label_name}


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------

def run_agent(service, max_threads: int, dry_run: bool, verbose: bool) -> None:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    label_map = resolve_label_ids(service)
    triage_label_ids = set(label_map.values())

    stats = {"labeled": 0, "skipped": 0}
    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                f"Please triage my unread Gmail inbox. "
                f"Process up to {max_threads} threads. "
                + ("Do NOT actually apply labels (dry-run mode)." if dry_run else "Apply the labels for real.")
            ),
        }
    ]

    print(f"Starting Gmail triage agent (max_threads={max_threads}, dry_run={dry_run})\n")

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # Extract final text summary from Claude
            for block in response.content:
                if hasattr(block, "text"):
                    print("\nAgent summary:\n" + block.text)
            break

        if response.stop_reason != "tool_use":
            print(f"Unexpected stop_reason: {response.stop_reason}")
            break

        # Process tool calls
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input

            if verbose:
                print(f"  [{tool_name}] {json.dumps(tool_input, ensure_ascii=False)}")

            try:
                if tool_name == "search_unread_threads":
                    result = search_unread_threads(
                        service,
                        max_results=max_threads - stats["labeled"],
                        triage_label_ids=triage_label_ids,
                        page_token=tool_input.get("page_token"),
                    )
                elif tool_name == "get_thread":
                    result = get_thread(service, tool_input["thread_id"])
                elif tool_name == "apply_label":
                    result = apply_label(
                        service,
                        tool_input["thread_id"],
                        tool_input["label"],
                        label_map=label_map,
                        dry_run=dry_run,
                    )
                    label = tool_input["label"]
                    reason = tool_input.get("reason", "")
                    stats["labeled"] += 1
                    marker = "[DRY-RUN] " if dry_run else ""
                    print(f"{marker}{label:14s}  {reason}")
                else:
                    result = {"error": f"Unknown tool: {tool_name}"}
            except Exception as exc:
                result = {"error": str(exc)}

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

            # Stop if we've hit the thread limit
            if stats["labeled"] >= max_threads:
                tool_results[-1]["content"] = json.dumps(
                    {"status": "limit_reached", "message": f"Max threads ({max_threads}) processed."}
                )
                break

        messages.append({"role": "user", "content": tool_results})

    print(f"\nDone. Labeled: {stats['labeled']} threads.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Gmail triage agent powered by Claude")
    parser.add_argument("--max-threads", type=int, default=30, help="Max threads to process (default: 30)")
    parser.add_argument("--dry-run", action="store_true", help="Classify without applying labels")
    parser.add_argument("--verbose", action="store_true", help="Show every tool call")
    parser.add_argument("--user", default=None, help="User ID for multi-user setups (scopes secrets to gmail-agent/{user})")
    parser.add_argument(
        "--upload-token",
        action="store_true",
        help="Authenticate locally and upload OAuth token to AWS Secrets Manager (one-time setup per user)",
    )
    args = parser.parse_args()

    if args.user:
        set_user(args.user)

    if args.upload_token:
        upload_token_to_secrets_manager()
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ERROR: ANTHROPIC_API_KEY environment variable is not set.")

    service = get_gmail_service()
    run_agent(service, max_threads=args.max_threads, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    main()
