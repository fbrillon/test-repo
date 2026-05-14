#!/usr/bin/env python3
"""
Automated Claude code review for pull requests.

Fetches the PR diff and metadata via gh CLI, sends them to Claude,
then posts (or updates) a review comment on the PR.
"""

import json
import os
import subprocess
import sys

import anthropic

REVIEW_MARKER = "<!-- claude-review -->"
MAX_DIFF_CHARS = 20_000

SYSTEM_PROMPT = """\
You are an expert code reviewer. Your reviews are concise, specific, and actionable.
You focus on: correctness, security, performance, and maintainability.
You do not comment on style that is already handled by a linter.
Format your review in Markdown.
"""

REVIEW_PROMPT = """\
Review the following pull request.

## PR metadata
Title: {title}
Description:
{body}

## Changed files
{files}

## Diff
```diff
{diff}
```

Structure your review as:

### Summary
One paragraph describing what this PR does.

### Issues
Bullet list of bugs, security concerns, or logic errors found. \
If none, write "No issues found."

### Suggestions
Bullet list of optional improvements (performance, readability, edge cases). \
If none, write "No suggestions."

### Verdict
One of: ✅ **Approve** / ⚠️ **Approve with suggestions** / ❌ **Request changes**
"""


def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def get_pr_metadata(pr_number: str) -> dict:
    raw = run([
        "gh", "pr", "view", pr_number,
        "--json", "title,body,files",
    ])
    return json.loads(raw)


def get_diff(pr_number: str) -> str:
    diff = run(["gh", "pr", "diff", pr_number])
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n[diff truncated — too large to display in full]"
    return diff


def call_claude(title: str, body: str, files: list[dict], diff: str) -> str:
    file_list = "\n".join(f"- {f['path']}" for f in files) or "(none)"
    prompt = REVIEW_PROMPT.format(
        title=title,
        body=body or "(no description)",
        files=file_list,
        diff=diff,
    )
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def find_existing_comment(pr_number: str, repo: str) -> int | None:
    """Return the ID of an existing Claude review comment, or None."""
    raw = run([
        "gh", "api",
        f"/repos/{repo}/issues/{pr_number}/comments",
        "--jq", f'[.[] | select(.body | startswith("{REVIEW_MARKER}"))][0].id',
    ])
    return int(raw) if raw and raw != "null" else None


def post_or_update_comment(pr_number: str, repo: str, body: str) -> None:
    full_body = f"{REVIEW_MARKER}\n{body}"
    comment_id = find_existing_comment(pr_number, repo)

    if comment_id:
        subprocess.run([
            "gh", "api", "--method", "PATCH",
            f"/repos/{repo}/issues/comments/{comment_id}",
            "-f", f"body={full_body}",
        ], check=True)
        print(f"Updated existing review comment #{comment_id}")
    else:
        subprocess.run([
            "gh", "pr", "comment", pr_number,
            "--body", full_body,
        ], check=True)
        print("Posted new review comment")


def main() -> None:
    pr_number = os.environ.get("PR_NUMBER")
    repo = os.environ.get("REPO")

    if not pr_number or not repo:
        sys.exit("ERROR: PR_NUMBER and REPO environment variables must be set.")

    print(f"Reviewing PR #{pr_number} in {repo} …")

    meta = get_pr_metadata(pr_number)
    diff = get_diff(pr_number)

    review = call_claude(
        title=meta["title"],
        body=meta.get("body", ""),
        files=meta.get("files", []),
        diff=diff,
    )

    post_or_update_comment(pr_number, repo, review)
    print("Done.")


if __name__ == "__main__":
    main()
