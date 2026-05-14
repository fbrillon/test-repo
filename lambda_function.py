"""
AWS Lambda entry point for the Gmail Email Labeling Agent.

Triggered by EventBridge Scheduler on a cron schedule.
Gmail OAuth token is stored in and auto-refreshed to AWS Secrets Manager.
"""

import json
import logging
import os

import boto3

from agent import run_agent
from gmail_auth import get_gmail_service

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _load_anthropic_key() -> None:
    """Pull the Anthropic API key from Secrets Manager on cold start."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    prefix = os.environ.get("SECRET_PREFIX", "gmail-agent")
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("secretsmanager", region_name=region)
    secret = client.get_secret_value(SecretId=f"{prefix}/anthropic-api-key")["SecretString"]
    os.environ["ANTHROPIC_API_KEY"] = secret


def handler(event: dict, context) -> dict:
    os.environ.setdefault("LAMBDA_MODE", "1")
    _load_anthropic_key()

    max_threads = int(os.environ.get("MAX_THREADS", "50"))
    dry_run = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

    logger.info("Starting Gmail triage agent (max_threads=%d, dry_run=%s)", max_threads, dry_run)

    service = get_gmail_service()
    run_agent(service, max_threads=max_threads, dry_run=dry_run, verbose=True)

    return {"statusCode": 200, "body": json.dumps("Triage complete")}
