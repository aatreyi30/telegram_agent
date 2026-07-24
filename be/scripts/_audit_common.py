"""Shared plumbing for the audit_*.py scripts (trust-checks for dashboard numbers).

Each audit_*.py recomputes one page's numbers a second, INDEPENDENT way — raw
sqlite3 SQL, not the ORM, not the app's own aggregation code — and diffs the
two. This module holds the one piece of logic every one of them needs and
would otherwise duplicate (and re-break): converting an IST date range to the
UTC datetime strings SQLite will actually compare correctly against.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

IST_OFFSET = timedelta(hours=5, minutes=30)


def ist_range_to_sqlite_utc(start_iso: str, end_iso: str) -> tuple[str, str]:
    """[start_iso, end_iso] inclusive IST dates -> UTC datetime strings SQLite
    will compare correctly against a TEXT ``posted_at`` column.

    Two things this gets right on purpose, both discovered the hard way:
      1. IST offset (+5:30) applied by hand, not imported from periods.py — an
         audit script that reused the app's own IST math couldn't catch a bug
         in that math.
      2. sep=" " — posted_at is stored as TEXT with a SPACE separator
         ("2026-07-02 21:31:33.000000", Python sqlite3's default datetime
         adapter — the same one SQLAlchemy's DBAPI layer uses). SQLite compares
         that column lexicographically, so a 'T'-separated bound (isoformat()'s
         default) sorts wrong against it — space (0x20) < 'T' (0x54) — and
         silently drops real rows. Cost a debugging session to find once already;
         don't reintroduce it in a new script.
    """
    start_utc = (datetime.fromisoformat(start_iso) - IST_OFFSET).isoformat(sep=" ")
    end_utc = (datetime.fromisoformat(end_iso) + timedelta(days=1) - IST_OFFSET).isoformat(sep=" ")
    return start_utc, end_utc


def db_path() -> str:
    from src.config.settings import get_settings

    return get_settings().db_url.split("///", 1)[-1]
