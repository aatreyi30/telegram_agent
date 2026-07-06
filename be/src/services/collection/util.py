"""Small collection helpers shared across collectors."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
_ABBREV_RE = re.compile(r"^([\d,.]+)\s*([kKmM]?)$")


def content_hash(*parts: object) -> str:
    joined = "".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def extract_urls(text: str | None) -> list[str]:
    """Observe raw URLs in text. Pure extraction — no interpretation (Phase 2)."""
    if not text:
        return []
    seen: list[str] = []
    for m in _URL_RE.findall(text):
        url = m.rstrip(".,);]")
        if url not in seen:
            seen.append(url)
    return seen


def parse_abbreviated_int(value: str | None) -> int | None:
    """Parse Telegram's abbreviated counts ("12.3K", "1.2M") to an int.

    Returns None when the value cannot be parsed — never guesses.
    """
    if value is None:
        return None
    v = value.strip().replace(" ", "")
    if not v:
        return None
    m = _ABBREV_RE.match(v)
    if not m:
        digits = re.sub(r"[^\d]", "", v)
        return int(digits) if digits else None
    num, suffix = m.groups()
    try:
        base = float(num.replace(",", ""))
    except ValueError:
        return None
    factor = {"": 1, "k": 1_000, "m": 1_000_000}[suffix.lower()]
    return int(round(base * factor))


def to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
