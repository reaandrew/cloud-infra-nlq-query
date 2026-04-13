"""
API Gateway v2 Lambda authoriser (REQUEST type, simple-response format).

Checks the inbound `x-api-key` header against a value held in AWS Secrets
Manager. The secret value is fetched once per cold start and cached
in-process — combined with the authoriser's response cache (5 min) at
the API Gateway level, this keeps the GetSecretValue call rate near zero.

Environment variables:
  API_KEY_SECRET_ARN  ARN of the secret holding the expected API key value
"""

from __future__ import annotations

import logging
import os

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

API_KEY_SECRET_ARN = os.environ["API_KEY_SECRET_ARN"]

_SM = boto3.client("secretsmanager")
_CACHED_KEY: str | None = None


def _expected_key() -> str:
    global _CACHED_KEY
    if _CACHED_KEY is None:
        resp = _SM.get_secret_value(SecretId=API_KEY_SECRET_ARN)
        _CACHED_KEY = resp["SecretString"].strip()
    return _CACHED_KEY


def _header(headers: dict, name: str) -> str | None:
    if not headers:
        return None
    needle = name.lower()
    for k, v in headers.items():
        if k.lower() == needle:
            return v
    return None


def handler(event, context):
    expected = _expected_key()
    headers = event.get("headers") or {}
    presented = _header(headers, "x-api-key")
    authorized = bool(presented) and presented.strip() == expected
    if not authorized:
        log.warning("auth denied (presented_len=%d)", len(presented or ""))
    return {"isAuthorized": authorized}
