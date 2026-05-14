"""
Gmail authentication — supports both local OAuth (browser) and Lambda (Secrets Manager).

Local mode  : reads credentials.json + token.pickle from disk.
Lambda mode : reads/writes credentials and token from AWS Secrets Manager.
              Set LAMBDA_MODE=1 to activate.
"""

import json
import os
import pickle
import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


# ---------------------------------------------------------------------------
# Lambda mode — Secrets Manager
# ---------------------------------------------------------------------------

def _sm_client():
    import boto3
    return boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))


_USER_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def set_user(user_id: str) -> None:
    """Scope all Secrets Manager keys to a specific user. Call before get_gmail_service()."""
    if not _USER_ID_RE.match(user_id):
        raise ValueError(
            f"Invalid user_id {user_id!r}. "
            "Only alphanumerics, hyphens and underscores are allowed (max 64 chars)."
        )
    os.environ["SECRET_PREFIX"] = f"gmail-agent/{user_id}"


def _secret_name(key: str) -> str:
    prefix = os.environ.get("SECRET_PREFIX", "gmail-agent")
    return f"{prefix}/{key}"


def _get_secret(key: str) -> str:
    return _sm_client().get_secret_value(SecretId=_secret_name(key))["SecretString"]


def _put_secret(key: str, value: str) -> None:
    client = _sm_client()
    name = _secret_name(key)
    try:
        client.put_secret_value(SecretId=name, SecretString=value)
    except client.exceptions.ResourceNotFoundException:
        client.create_secret(Name=name, SecretString=value)


def _creds_from_json(token_json: str) -> Credentials:
    data = json.loads(token_json)
    return Credentials(
        token=data.get("token"),
        refresh_token=data["refresh_token"],
        token_uri=data["token_uri"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=data.get("scopes", SCOPES),
    )


def _creds_to_json(creds: Credentials) -> str:
    return json.dumps({
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    })


def _get_lambda_credentials() -> Credentials:
    token_json = _get_secret("token")
    creds = _creds_from_json(token_json)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Persist refreshed token back to Secrets Manager
            _put_secret("token", _creds_to_json(creds))
        else:
            raise RuntimeError(
                "Gmail token is invalid and cannot be refreshed automatically. "
                "Run `python agent.py --upload-token` locally to re-authenticate."
            )
    return creds


# ---------------------------------------------------------------------------
# Local mode — disk
# ---------------------------------------------------------------------------

def _get_local_credentials(
    credentials_path: str = "credentials.json",
    token_path: str = "token.pickle",
) -> Credentials:
    creds = None
    if Path(token_path).exists():
        with open(token_path, "rb") as f:
            creds = pickle.load(f)  # nosec B301 — file written by this process, not from network

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not Path(credentials_path).exists():
                raise FileNotFoundError(
                    f"{credentials_path} not found. "
                    "Download OAuth credentials from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    return creds


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_gmail_service(
    credentials_path: str = "credentials.json",
    token_path: str = "token.pickle",
):
    """Return an authenticated Gmail API service client."""
    if os.environ.get("LAMBDA_MODE"):
        creds = _get_lambda_credentials()
    else:
        creds = _get_local_credentials(credentials_path, token_path)
    return build("gmail", "v1", credentials=creds)


def upload_token_to_secrets_manager(
    credentials_path: str = "credentials.json",
    token_path: str = "token.pickle",
) -> None:
    """
    One-time setup helper: authenticate locally, then upload credentials and
    token to AWS Secrets Manager so Lambda can use them.

    Run locally:  python agent.py --upload-token
    """
    creds = _get_local_credentials(credentials_path, token_path)
    _put_secret("token", _creds_to_json(creds))

    with open(credentials_path) as f:
        _put_secret("credentials", f.read())

    print(f"Uploaded secrets to AWS Secrets Manager under prefix '{os.environ.get('SECRET_PREFIX', 'gmail-agent')}'.")
    print("You can now deploy the Lambda function.")
