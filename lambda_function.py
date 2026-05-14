"""
AWS Lambda entry point for the Gmail Email Labeling Agent.

Triggered by EventBridge Scheduler. Each schedule passes its user_id in the
event payload so a single Lambda deployment serves multiple users:

    {"user_id": "alice"}

For single-user deployments, omit user_id (falls back to the gmail-agent/ prefix).
"""

import json
import logging
import os

import boto3

from agent import run_agent
from gmail_auth import get_gmail_service, set_user

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_anthropic_key_loaded = False


def _load_anthropic_key() -> None:
    global _anthropic_key_loaded
    if _anthropic_key_loaded or os.environ.get("ANTHROPIC_API_KEY"):
        return
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("secretsmanager", region_name=region)
    key = client.get_secret_value(SecretId="gmail-agent/anthropic-api-key")["SecretString"]
    os.environ["ANTHROPIC_API_KEY"] = key
    _anthropic_key_loaded = True


def handler(event: dict, context) -> dict:
    os.environ.setdefault("LAMBDA_MODE", "1")
    _load_anthropic_key()

    user_id = event.get("user_id") or os.environ.get("USER_ID", "")
    if user_id:
        set_user(user_id)
        logger.info("Running triage for user: %s", user_id)
    else:
        logger.info("Running triage (single-user mode)")

    max_threads = int(event.get("max_threads") or os.environ.get("MAX_THREADS", "50"))
    dry_run = bool(event.get("dry_run") or os.environ.get("DRY_RUN", ""))

    service = get_gmail_service()
    run_agent(service, max_threads=max_threads, dry_run=dry_run, verbose=True)

    return {"statusCode": 200, "body": json.dumps({"status": "ok", "user_id": user_id or "default"})}


    max_threads = int(os.environ.get("MAX_THREADS", "50"))
    dry_run = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

    logger.info("Starting Gmail triage agent (max_threads=%d, dry_run=%s)", max_threads, dry_run)

    service = get_gmail_service()
    run_agent(service, max_threads=max_threads, dry_run=dry_run, verbose=True)

    return {"statusCode": 200, "body": json.dumps("Triage complete")}
