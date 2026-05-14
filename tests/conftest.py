"""
Patch heavy third-party modules before any test imports agent.py or gmail_auth.py.
This lets unit tests run without installing google-auth, anthropic, or boto3.
"""

import sys
from unittest.mock import MagicMock

for mod in [
    "anthropic",
    "boto3",
    "dotenv",
    "google",
    "google.auth",
    "google.auth.transport",
    "google.auth.transport.requests",
    "google.oauth2",
    "google.oauth2.credentials",
    "google_auth_oauthlib",
    "google_auth_oauthlib.flow",
    "googleapiclient",
    "googleapiclient.discovery",
]:
    sys.modules.setdefault(mod, MagicMock())
