"""Authentication — stdlib-only (no bcrypt/JWT libs; this box has no compiler).

Passwords: PBKDF2-HMAC-SHA256 with a random per-password salt (``security``).
Tokens:    compact HMAC-SHA256 signed tokens with an expiry (``tokens``).
FastAPI:   ``deps`` exposes ``current_user`` / ``require_role`` dependencies.

Adequate for a local, single-org tool. Not hardened for public multi-tenant hosting.
"""

from src.auth.security import hash_password, verify_password
from src.auth.tokens import issue_token, verify_token

__all__ = ["hash_password", "verify_password", "issue_token", "verify_token"]
