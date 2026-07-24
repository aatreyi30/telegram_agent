"""Independently verify the /day (Day view) per-merchant table against raw SQLite.

Same idea as audit_analytics.py, applied to services/analytics/day.py:summarize()
instead of views.py:compute(). Recomputes each merchant row's post_count,
total_views, total_reactions, total_forwards, engagement_rate, deal_count a
second, INDEPENDENT way (raw sqlite3, not the ORM, not day.py's own code) and
diffs against what the live app actually returns.

Usage (from the be/ directory, venv active):
    python scripts/audit_day.py --start 2025-07-10 --end 2026-07-10   # "All"
    python scripts/audit_day.py --start 2026-07-01 --end 2026-07-10
    python scripts/audit_day.py --selfcheck
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict

from _audit_common import db_path, ist_range_to_sqlite_utc


def _reduce_by_merchant(rows: list[tuple]) -> dict[str, dict]:
    """rows: (views, reactions, forwards, merchant_key, has_coupon, is_multi_deal)."""
    buckets: dict[str, dict] = defaultdict(lambda: {
        "post_count": 0, "total_views": 0, "total_reactions": 0,
        "total_forwards": 0, "deal_count": 0,
    })
    for views, reactions, forwards, mk, has_coupon, is_multi_deal in rows:
        key = mk or "Unknown"
        b = buckets[key]
        b["post_count"] += 1
        b["total_views"] += views or 0
        b["total_reactions"] += reactions or 0
        b["total_forwards"] += forwards or 0
        if has_coupon or is_multi_deal:
            b["deal_count"] += 1
    for b in buckets.values():
        tv = b["total_views"]
        eng = b["total_reactions"] + b["total_forwards"]
        b["engagement_rate"] = round(eng / tv * 100, 1) if tv else None
    return buckets


def raw_recompute(dbp: str, start_iso: str, end_iso: str) -> dict[str, dict]:
    start_utc, end_utc = ist_range_to_sqlite_utc(start_iso, end_iso)
    con = sqlite3.connect(dbp)
    cur = con.cursor()
    cur.execute(
        """
        SELECT p.views, p.reactions_total, p.forwards, np.primary_merchant_key,
               np.has_coupon, np.is_multi_deal
        FROM posts p
        JOIN normalized_posts np ON np.source_id = p.id AND np.source_type = 'owned'
        WHERE p.posted_at >= ? AND p.posted_at < ?
        """,
        (start_utc, end_utc),
    )
    rows = cur.fetchall()
    con.close()
    return _reduce_by_merchant(rows)


def audit(start_iso: str, end_iso: str) -> bool:
    from datetime import date as _date

    from src.controllers.service import day_summary

    api = day_summary(day=_date.fromisoformat(start_iso), end=_date.fromisoformat(end_iso))
    if not api.get("available"):
        print(f"API returned available=False: {api.get('note')}")
        return False

    raw = raw_recompute(db_path(), start_iso, end_iso)
    api_by_key = {(m["key"] or "Unknown"): m for m in api["merchants"]}

    all_keys = sorted(set(api_by_key) | set(raw))
    print(f"Audit window: {start_iso} -> {end_iso} (IST)\n")
    print(f"{'merchant':<16}{'field':<18}{'dashboard':>12}{'raw-sql':>12}  status")
    ok = True
    fields = ["post_count", "total_views", "total_reactions", "total_forwards",
              "engagement_rate", "deal_count"]
    for key in all_keys:
        a = api_by_key.get(key, {})
        r = raw.get(key, {})
        for f in fields:
            av, rv = a.get(f), r.get(f)
            match = av == rv
            ok = ok and match
            print(f"{key:<16}{f:<18}{str(av):>12}{str(rv):>12}  {'OK' if match else 'MISMATCH <<<'}")

    print()
    print("PASS: every merchant row matches an independent raw-SQL recomputation." if ok
          else "FAIL: day.py's merchant table does NOT match raw data.")
    return ok


def _selfcheck() -> None:
    rows = [
        (100, 5, 1, "amazon", False, False),
        (200, 0, 0, "amazon", True, False),
        (50, 2, 0, None, False, True),
    ]
    b = _reduce_by_merchant(rows)
    assert b["amazon"]["post_count"] == 2, b
    assert b["amazon"]["total_views"] == 300, b
    assert b["amazon"]["deal_count"] == 1, b
    assert b["Unknown"]["post_count"] == 1, b
    assert b["Unknown"]["deal_count"] == 1, b
    print("selfcheck OK")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--start", help="IST date YYYY-MM-DD")
    p.add_argument("--end", help="IST date YYYY-MM-DD")
    p.add_argument("--selfcheck", action="store_true")
    args = p.parse_args()

    if args.selfcheck:
        _selfcheck()
        sys.exit(0)

    if not (args.start and args.end):
        print("Pass --start and --end (IST dates). Use the /day-range you're checking on the UI.")
        sys.exit(2)

    sys.exit(0 if audit(args.start, args.end) else 1)
