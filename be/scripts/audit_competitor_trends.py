"""Independently verify the Competitors page's daily trend chart against raw SQLite.

Covers services/analytics/competitor_trends.py:dashboard_trends() — the
per-competitor posts/day and views/day series shown on /competitors. Recomputes
the same per-(competitor, day) counts a second, INDEPENDENT way (raw sqlite3)
and diffs against what the live app returns.

Does NOT cover the "full window" competitor comparison table (avg_views_per_post,
cta_rate, deal_mix, etc. on /competitors) — those numbers come from
CompetitorProfile, a table built by a separate batch job (competitor_intel), not
computed live from raw posts at request time. Auditing that means re-running the
intelligence engine and diffing against its own stored output — a different,
bigger check (see audit_competitor_comparison.py for the one slice of that page
that IS live-computed: the window-filtered mode).

Usage (from the be/ directory, venv active):
    python scripts/audit_competitor_trends.py --days 30
    python scripts/audit_competitor_trends.py --selfcheck
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import timedelta

from _audit_common import db_path


def _bucket(rows: list[tuple]) -> tuple[dict, dict]:
    """rows: (competitor_id, posted_at_str, views). posted_at_str: 'YYYY-MM-DD ...' (IST-shifted already)."""
    post_counts: dict[tuple[int, str], int] = defaultdict(int)
    view_totals: dict[tuple[int, str], int] = defaultdict(int)
    for cid, posted_at_str, views in rows:
        if not posted_at_str:
            continue
        day = posted_at_str[:10]
        post_counts[(cid, day)] += 1
        view_totals[(cid, day)] += views or 0
    return post_counts, view_totals


def raw_recompute(dbp: str, days: int) -> tuple[dict, dict, str, str]:
    """Mirrors dashboard_trends()'s own window logic: anchored to the latest
    CompetitorPost date across ALL competitors, not "today"."""
    con = sqlite3.connect(dbp)
    cur = con.cursor()

    # IST shift done in SQL itself (+5:30 = +330 minutes), so day-bucketing matches
    # to_ist().date() without importing periods.py — an independent recompute
    # can't reuse the app's own IST-conversion code, or a bug there goes uncaught.
    cur.execute("SELECT MAX(datetime(posted_at, '+330 minutes')) FROM competitor_posts")
    end_ist = cur.fetchone()[0]
    if not end_ist:
        con.close()
        return {}, {}, "", ""
    end_day = end_ist[:10]
    from datetime import date as _date
    first_day = (_date.fromisoformat(end_day) - timedelta(days=days - 1)).isoformat()

    cur.execute(
        """
        SELECT competitor_id, datetime(posted_at, '+330 minutes'), views
        FROM competitor_posts
        WHERE datetime(posted_at, '+330 minutes') >= ? AND datetime(posted_at, '+330 minutes') < ?
        """,
        (first_day + " 00:00:00", (_date.fromisoformat(end_day) + timedelta(days=1)).isoformat() + " 00:00:00"),
    )
    rows = cur.fetchall()
    con.close()
    post_counts, view_totals = _bucket(rows)
    return post_counts, view_totals, first_day, end_day


def audit(days: int) -> bool:
    from src.db.session import session_scope
    from src.services.analytics.competitor_trends import dashboard_trends

    with session_scope() as s:
        api = dashboard_trends(s, days=days)
    if not api["dates"]:
        print("API returned no data (no competitor posts collected).")
        return False

    raw_posts, raw_views, first_day, end_day = raw_recompute(db_path(), days)
    print(f"Audit window: {first_day} -> {end_day} (IST), {days} days, "
          f"{len(api['competitors'])} competitors\n")

    id_by_name = {c["name"]: c["id"] for c in api["competitors"]}
    ok = True
    mismatches = 0
    for prow, vrow in zip(api["posting_trend"], api["views_trend"]):
        day = prow["date"]
        for name, cid in id_by_name.items():
            api_posts = prow.get(name, 0)
            api_views = vrow.get(name, 0)
            raw_p = raw_posts.get((cid, day), 0)
            raw_v = raw_views.get((cid, day), 0)
            if api_posts != raw_p or api_views != raw_v:
                ok = False
                mismatches += 1
                print(f"  MISMATCH {day} {name}: posts dashboard={api_posts} raw={raw_p}, "
                      f"views dashboard={api_views} raw={raw_v}")

    print()
    print("PASS: every competitor/day cell matches an independent raw-SQL recomputation." if ok
          else f"FAIL: {mismatches} (competitor, day) cells do NOT match raw data.")
    return ok


def _selfcheck() -> None:
    rows = [
        (1, "2026-07-01 10:00:00", 100),
        (1, "2026-07-01 14:00:00", 50),
        (2, "2026-07-02 09:00:00", 200),
    ]
    posts, views = _bucket(rows)
    assert posts[(1, "2026-07-01")] == 2
    assert views[(1, "2026-07-01")] == 150
    assert posts[(2, "2026-07-02")] == 1
    assert views[(2, "2026-07-02")] == 200
    print("selfcheck OK")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--selfcheck", action="store_true")
    args = p.parse_args()

    if args.selfcheck:
        _selfcheck()
        sys.exit(0)

    sys.exit(0 if audit(args.days) else 1)
