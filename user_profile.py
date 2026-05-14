"""
User classification profile — anonymized behavioral patterns, no PII.

Stored locally as profiles/{user_id}.json or in Secrets Manager on Lambda.
The profile is injected into Claude's system prompt to improve classification accuracy.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class UserProfile:
    schema_version: int = 1
    created_at: str = field(default_factory=lambda: str(date.today()))
    updated_at: str = field(default_factory=lambda: str(date.today()))
    emails_analyzed: int = 0
    label_distribution: dict = field(default_factory=dict)
    # Anonymized behavioral patterns extracted by Claude — no PII
    patterns: list = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "UserProfile":
        data = json.loads(raw)
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_prompt_context(self) -> str:
        """Format profile as additional context for Claude's system prompt."""
        if not self.emails_analyzed:
            return ""
        lines = [
            "## User Classification Profile",
            f"Learned from {self.emails_analyzed} historical emails.",
        ]
        if self.label_distribution:
            lines.append("\nTypical label distribution:")
            for label, pct in sorted(self.label_distribution.items(), key=lambda x: -x[1]):
                lines.append(f"  {label}: {pct:.0%}")
        if self.patterns:
            lines.append("\nLearned patterns — apply these when classifying:")
            for p in self.patterns:
                lines.append(f"  - {p}")
        lines.append(
            "\nUse the profile as a prior: when signals are ambiguous, "
            "prefer the label consistent with these patterns."
        )
        return "\n".join(lines)


# Prompt used by profiler.py to extract an anonymized profile
PROFILE_EXTRACTION_PROMPT = """\
You are analyzing anonymized signals from a sample of emails to build a \
classification profile for improving future triage accuracy.

Each email is represented only by structural signals — no names, addresses, \
subjects, or message content are included.

Analyze the patterns and return a JSON object with EXACTLY this schema:
{
  "emails_analyzed": <integer>,
  "label_distribution": {
    "Act_Now": <float 0-1>,
    "Next_Moves": <float 0-1>,
    "Track_It": <float 0-1>,
    "Stay_Informed": <float 0-1>,
    "Skip_It": <float 0-1>
  },
  "patterns": [
    <5 to 10 short strings describing anonymized behavioral patterns>
  ]
}

Rules for the "patterns" field — each string MUST:
- Be a general behavioral observation, not a specific fact
- Contain NO email addresses, names, domains, or company names
- Contain NO email subjects or message fragments
- Focus on: sender types, structural signals, interaction patterns, thread characteristics

Good examples:
  "Automated service notifications are consistently Skip_It"
  "Emails with direct questions addressed to the user require action"
  "Multi-message threads with back-and-forth are usually Act_Now"
  "Single-message threads from services are typically Track_It or Skip_It"

Bad examples (contain PII or specifics):
  "Emails from john@company.com are Act_Now"  ← contains address
  "Subject 'Invoice #1234' → Track_It"         ← contains content
  "company.com newsletters → Skip_It"           ← contains domain

Return ONLY valid JSON. No markdown fences, no explanation outside the JSON.
"""


# ---------------------------------------------------------------------------
# Storage — dual mode: local disk / AWS Secrets Manager
# ---------------------------------------------------------------------------

def _secret_name_for_profile(user_id: str) -> str:
    prefix = os.environ.get("SECRET_PREFIX", f"gmail-agent/{user_id}" if user_id else "gmail-agent")
    return f"{prefix}/profile"


def load_profile(user_id: str = "") -> "UserProfile | None":
    if os.environ.get("LAMBDA_MODE"):
        return _load_lambda(user_id)
    return _load_local(user_id)


def save_profile(profile: "UserProfile", user_id: str = "") -> None:
    profile.updated_at = str(date.today())
    if os.environ.get("LAMBDA_MODE"):
        _save_lambda(profile, user_id)
    else:
        _save_local(profile, user_id)


def _profile_path(user_id: str) -> Path:
    return Path("profiles") / f"{user_id or 'default'}.json"


def _load_local(user_id: str) -> "UserProfile | None":
    path = _profile_path(user_id)
    if path.exists():
        return UserProfile.from_json(path.read_text())
    return None


def _save_local(profile: "UserProfile", user_id: str) -> None:
    path = _profile_path(user_id)
    path.parent.mkdir(exist_ok=True)
    path.write_text(profile.to_json())


def _load_lambda(user_id: str) -> "UserProfile | None":
    try:
        import boto3
        client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        raw = client.get_secret_value(SecretId=_secret_name_for_profile(user_id))["SecretString"]
        return UserProfile.from_json(raw)
    except Exception:
        return None


def _save_lambda(profile: "UserProfile", user_id: str) -> None:
    import boto3
    client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    name = _secret_name_for_profile(user_id)
    try:
        client.put_secret_value(SecretId=name, SecretString=profile.to_json())
    except client.exceptions.ResourceNotFoundException:
        client.create_secret(Name=name, SecretString=profile.to_json())
