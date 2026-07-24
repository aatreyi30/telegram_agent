"""Independently verify the /analytics dashboard numbers against raw SQLite.

Why this exists: the dashboard's numbers (Posts, Views, Total reactions, Total
forwards, Eng. rate, CTA rate, Deal rate) all come from ONE code path —
services/analytics/views.py:compute(). If that code has a bug, the dashboard
is silently wrong and nothing catches it. This script recomputes the same
numbers a second, INDEPENDENT way — raw sqlite3 SQL, not the ORM, not
views.py's helper functions — and diffs the two. A mismatch means the
dashboard's aggregation logic has drifted from the raw data.

It also surfaces what the dashboard silently EXCLUDES (owned posts with no
normalized_posts row yet, or with views still NULL) — the "Posts: 394" number
is not "everything on the channel", it's "everything counted so far".

Usage (from the be/ directory, venv active):
    python scripts/audit_analytics.py                        # default: last 7 IST days
    python scripts/audit_analytics.py --start 2026-07-03 --end 2026-07-10
    python scripts/audit_analytics.py --days 30
    python scripts/audit_analytics.py --selfcheck             # no DB needed
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, timedelta

from _audit_common import db_path, ist_range_to_sqlite_utc

FIELD_MAP = {
    # dashboard/API field -> raw-recompute field
    "total_posts": "n",
    "total_views": "total_views",
    "total_reactions": "total_reactions",
    "total_forwards": "total_forwards",
    "engagement_rate": "engagement_rate",
    "cta_rate": "cta_rate",
    "deal_rate": "deal_rate",
}


def _reduce(rows: list[tuple]) -> dict:
    """rows: (views, reactions, forwards, cta_texts_json, has_coupon, is_multi_deal)."""
    n = len(rows)
    views = sum(r[0] or 0 for r in rows)
    reactions = sum(r[1] or 0 for r in rows)
    forwards = sum(r[2] or 0 for r in rows)
    cta_posts = sum(1 for r in rows if r[3] and json.loads(r[3]))
    deal_posts = sum(1 for r in rows if r[4] or r[5])
    engagement = reactions + forwards
    return {
        "n": n,
        "total_views": views,
        "total_reactions": reactions,
        "total_forwards": forwards,
        "engagement_rate": round(engagement / views * 100, 1) if views else 0,
        "cta_rate": round(cta_posts / n * 100, 1) if n else 0,
        "deal_rate": round(deal_posts / n * 100, 1) if n else 0,
    }


def raw_recompute(dbp: str, start_iso: str, end_iso: str) -> dict:
    """Hits the sqlite file directly with plain SQL — bypasses the ORM/session/views.py entirely."""
    start_utc, end_utc = ist_range_to_sqlite_utc(start_iso, end_iso)

    con = sqlite3.connect(dbp)
    cur = con.cursor()
    cur.execute(
        """
        SELECT p.views, p.reactions_total, p.forwards, np.cta_texts, np.has_coupon, np.is_multi_deal
        FROM posts p
        JOIN normalized_posts np ON np.source_id = p.id AND np.source_type = 'owned'
        WHERE p.views IS NOT NULL AND p.posted_at IS NOT NULL
          AND p.posted_at >= ? AND p.posted_at < ?
        """,
        (start_utc, end_utc),
    )
    rows = cur.fetchall()
    result = _reduce(rows)

    cur.execute(
        """
        SELECT COUNT(*) FROM posts p
        WHERE p.posted_at >= ? AND p.posted_at < ?
          AND NOT EXISTS (
            SELECT 1 FROM normalized_posts np
            WHERE np.source_id = p.id AND np.source_type = 'owned'
          )
        """,
        (start_utc, end_utc),
    )
    result["unnormalized_excluded"] = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(*) FROM posts p WHERE p.posted_at >= ? AND p.posted_at < ? AND p.views IS NULL",
        (start_utc, end_utc),
    )
    result["missing_views_excluded"] = cur.fetchone()[0]
    con.close()
    return result


def audit(start_iso: str, end_iso: str) -> bool:
    from src.controllers.service import analytics as api_analytics

    api = api_analytics(start=start_iso, end=end_iso)
    raw = raw_recompute(db_path(), start_iso, end_iso)

    print(f"Audit window: {start_iso} -> {end_iso} (IST)\n")
    print(f"{'metric':<18}{'dashboard':>12}{'raw-sql':>12}  status")
    ok = True
    for api_key, raw_key in FIELD_MAP.items():
        a, r = api[api_key], raw[raw_key]
        match = a == r
        ok = ok and match
        print(f"{api_key:<18}{a:>12}{r:>12}  {'OK' if match else 'MISMATCH <<<'}")

    print()
    if raw["unnormalized_excluded"]:
        print(f"  {raw['unnormalized_excluded']} owned posts in this window have NO normalized_posts row "
              f"-> silently excluded from every number above (not counted in 'Posts').")
    if raw["missing_views_excluded"]:
        print(f"  {raw['missing_views_excluded']} owned posts in this window have views=NULL "
              f"-> silently excluded (not yet scraped, or the scrape failed).")
    if raw["n"] < 10:
        print(f"  Sample size n={raw['n']} is small — rates (CTA/deal/engagement) are noisy below n=10.")

    print()
    print("PASS: dashboard numbers match an independent raw-SQL recomputation." if ok
          else "FAIL: dashboard numbers do NOT match raw data. views.py has drifted from the DB.")
    return ok


def _selfcheck() -> None:
    """Smallest runnable check: _reduce()'s math against a hand-built fixture, no DB needed."""
    rows = [
        (100, 5, 1, '["Buy now"]', False, False),   # single deal, has CTA
        (200, 0, 0, None, True, False),              # deal (coupon), no CTA
        (0, 0, 0, None, False, False),                # zero views -> excluded from engagement_rate denom logic only via total
    ]
    r = _reduce(rows)
    assert r["n"] == 3, r
    assert r["total_views"] == 300, r
    assert r["total_reactions"] == 5, r
    assert r["total_forwards"] == 1, r
    assert r["engagement_rate"] == round(6 / 300 * 100, 1), r
    assert r["cta_rate"] == round(1 / 3 * 100, 1), r
    assert r["deal_rate"] == round(1 / 3 * 100, 1), r
    print("selfcheck OK")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--start", help="IST date YYYY-MM-DD")
    p.add_argument("--end", help="IST date YYYY-MM-DD")
    p.add_argument("--days", type=int, default=7, help="window size ending today if --start/--end omitted")
    p.add_argument("--selfcheck", action="store_true")
    args = p.parse_args()

    if args.selfcheck:
        _selfcheck()
        sys.exit(0)

    if args.start and args.end:
        start, end = args.start, args.end
    else:
        end_d = date.today()
        start_d = end_d - timedelta(days=args.days)
        start, end = start_d.isoformat(), end_d.isoformat()

    sys.exit(0 if audit(start, end) else 1)
