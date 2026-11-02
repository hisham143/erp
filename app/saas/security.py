"""SaaS token helpers. Secrets must be supplied by the deployment environment."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta


ACCESS_TOKEN_SECONDS = 15 * 60
REFRESH_TOKEN_DAYS = 30


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _secret() -> bytes:
    value = os.getenv("ERP_AUTH_SECRET", "")
    if len(value) < 32:
        raise RuntimeError("ERP_AUTH_SECRET must contain at least 32 characters.")
    return value.encode("utf-8")


def create_access_token(identity_id: int, tenant_id: int) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": str(identity_id),
        "tid": int(tenant_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ACCESS_TOKEN_SECONDS)).timestamp()),
        "jti": secrets.token_hex(12),
    }
    header = _b64(b'{"alg":"HS256","typ":"JWT"}')
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    signature = hmac.new(_secret(), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(signature)}"


def decode_access_token(token: str) -> dict:
    try:
        header, body, signature = token.split(".")
        signing_input = f"{header}.{body}".encode("ascii")
        expected = _b64(hmac.new(_secret(), signing_input, hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid token signature.")
        payload = json.loads(
            base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        )
        if payload.get("exp", 0) <= int(datetime.utcnow().timestamp()):
            raise ValueError("Access token expired.")
        if not payload.get("sub") or not payload.get("tid"):
            raise ValueError("Invalid token claims.")
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid or expired access token.") from exc


def create_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
