"""Signed session tokens — compact HMAC-SHA256 (stdlib; no JWT dependency).

Format: ``base64url(json_payload).base64url(hmac_sha256(payload, secret))``.
Payload carries ``uid`` and ``exp`` (unix seconds). ``verify_token`` checks the
signature (constant-time) and expiry and returns the user id, or None.

``now`` is injectable so the logic is testable without wall-clock reliance.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from src.config.settings import get_settings

_DEFAULT_TTL = 7 * 24 * 3600  # 7 days


def _secret() -> bytes:
    s = get_settings()
    return (s.auth_secret or s.api_secret_key or "dealwing-dev-secret").encode("utf-8")


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(txt: str) -> bytes:
    pad = "=" * (-len(txt) % 4)
    return base64.urlsafe_b64decode(txt + pad)


def _sign(payload_b64: str) -> str:
    sig = hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64e(sig)


def issue_token(user_id: int, *, ttl_seconds: int = _DEFAULT_TTL, now: float | None = None) -> str:
    now = time.time() if now is None else now
    payload = {"uid": int(user_id), "exp": int(now + ttl_seconds)}
    payload_b64 = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{payload_b64}.{_sign(payload_b64)}"


def verify_token(token: str | None, *, now: float | None = None) -> int | None:
    if not token or "." not in token:
        return None
    payload_b64, _, sig = token.partition(".")
    if not hmac.compare_digest(sig, _sign(payload_b64)):
        return None
    try:
        payload = json.loads(_b64d(payload_b64))
    except (ValueError, json.JSONDecodeError):
        return None
    now = time.time() if now is None else now
    if int(payload.get("exp", 0)) < now:
        return None
    uid = payload.get("uid")
    return int(uid) if uid is not None else None
