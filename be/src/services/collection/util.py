"""Small collection helpers shared across collectors."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date as date_, datetime, timedelta, timezone

_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
_ABBREV_RE = re.compile(r"^([\d,.]+)\s*([kKmM]?)$")

# Duplicated (not imported) across the codebase — see e.g.
# services/analytics/periods.py::IST — rather than centralised, so this module
# stays dependency-free and independently unit-testable.
IST = timezone(timedelta(hours=5, minutes=30))


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


def parse_stats_graph_json(raw: str | None) -> list[tuple[date_, str, int]]:
    """Parse Telegram's Google-charts-style stats graph JSON into
    ``(date, source_label, value)`` rows.

    Telegram's ``stats.StatsGraph.json.data`` (from ``stats.getBroadcastStats``,
    e.g. ``views_by_source_graph`` / ``new_followers_by_source_graph``) looks like::

        {"columns": [["x", 1700000000000, 1700086400000],
                      ["y0", 120, 130],
                      ["y1", 45, 50]],
         "names": {"y0": "search", "y1": "channels"}}

    The ``"x"`` column holds millisecond Unix timestamps shared by every other
    ("y*") column, each of which is one named data series. Timestamps are
    interpreted as UTC instants and bucketed into IST calendar days, matching
    the rest of the app's "IST calendar day" convention (see
    ``services/analytics/periods.py::IST``).

    Pure function: never raises on malformed input, just returns fewer/no rows —
    nothing here is fabricated.
    """
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(payload, dict):
        return []

    columns = payload.get("columns")
    if not isinstance(columns, list):
        return []
    names = payload.get("names") if isinstance(payload.get("names"), dict) else {}

    x_values: list | None = None
    series: dict[str, list] = {}
    for col in columns:
        if not isinstance(col, list) or not col:
            continue
        col_id, *values = col
        if col_id == "x":
            x_values = values
        elif isinstance(col_id, str):
            series[col_id] = values

    if not x_values:
        return []

    rows: list[tuple[date_, str, int]] = []
    for col_id, values in series.items():
        label = str(names.get(col_id, col_id))
        for ts_ms, value in zip(x_values, values):
            if ts_ms is None or value is None:
                continue
            try:
                day = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).astimezone(IST).date()
            except (ValueError, OverflowError, OSError, TypeError):
                continue
            try:
                rows.append((day, label, int(value)))
            except (TypeError, ValueError):
                continue
    return rows
