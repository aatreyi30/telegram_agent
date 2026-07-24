"""Independently verify the /plan (Plan page) DETERMINISTIC numbers against raw SQLite.

Same idea as audit_day.py / audit_analytics.py / audit_competitor_trends.py, applied
to the Plan page. Recomputes each number a second, INDEPENDENT way (raw sqlite3, not
the ORM, not the app's own aggregation code) and diffs against what the live app
actually returns.

Scope — what this DOES and DOES NOT cover, on purpose:

  Covered (pure aggregation over real rows — independently re-derivable):
    * "Yesterday" card: posts_count, views_avg, engagement_rate, type_mix,
      best/worst merchant (by summed views) — see services/analytics/daily_report.py
    * "Today" recommended_posts — median posts/day over ACTIVE days in the last 14
      IST days ending at the latest owned post day — see ai/context.py:posting_trajectory
    * The "content_concentration" risk banner's stated percentage — majority
      single/loot share over the last 45 days — see services/planning/campaign.py:_risks

  NOT covered, and why a raw-SQL diff can't meaningfully cover them:
    * posting_windows / deal_type_allocation / merchant_mix targets — these come from
      CampaignPlanningEngine's recency+performance-blended SCORING (a weighted formula,
      not a sum), see campaign.py:_merchant_allocation / build_posting_plan. Re-deriving
      that here would just be a second, unverified implementation of the same formula —
      that's what tests/test_campaign_planning.py (unit tests against known inputs) are
      for, not this script.
    * The AI's per-slot "why" text and the daily narrative/digest — these are opinions
      grounded in real numbers, not numbers themselves. Their factual claims are
      verified by a SEPARATE mechanism: ai/factcheck.py cross-checks every number the
      AI cites against the actual facts it was shown, and the page surfaces the result
      as factcheck_status ("pass"/"warn"/"fallback") — that's the audit trail for the
      narrative, this script's is for the numbers underneath it.

Usage (from the be/ directory, venv active):
    python scripts/audit_plan.py --date 2026-07-24   # checks "yesterday" = the day before
    python scripts/audit_plan.py --selfcheck
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from datetime import date as date_cls, datetime, timedelta, timezone
from statistics import median

from _audit_common import db_path, ist_range_to_sqlite_utc


def _yesterday_raw(dbp: str, day_iso: str) -> dict:
    """Independently recompute the 'Yesterday' card for the IST date ``day_iso``."""
    start_utc, end_utc = ist_range_to_sqlite_utc(day_iso, day_iso)
    con = sqlite3.connect(dbp)
    cur = con.cursor()
    cur.execute(
        """
        SELECT p.views, p.reactions_total, p.forwards, np.primary_merchant_key,
               np.is_multi_deal
        FROM posts p
        JOIN normalized_posts np ON np.source_id = p.id AND np.source_type = 'owned'
        WHERE p.posted_at >= ? AND p.posted_at < ?
        """,
        (start_utc, end_utc),
    )
    rows = cur.fetchall()
    con.close()

    posts_count = len(rows)
    views = [v or 0 for v, *_ in rows]
    views_total = sum(views)
    reactions = sum(r or 0 for _, r, *_ in rows)
    forwards = sum(f or 0 for _, _, f, *_ in rows)
    type_mix = Counter("loot_deal" if multi else "single_deal" for *_, multi in rows)

    views_by_merchant: Counter = Counter()
    for v, _r, _f, mk, _multi in rows:
        views_by_merchant[mk or "__unknown__"] += (v or 0)
    best = max(views_by_merchant, key=views_by_merchant.get) if views_by_merchant else None
    worst = min(views_by_merchant, key=views_by_merchant.get) if views_by_merchant else None

    return {
        "posts_count": posts_count,
        "views_avg": round(views_total / posts_count, 2) if posts_count else 0.0,
        "engagement_rate": round((reactions + forwards) / views_total * 100, 2) if views_total else 0.0,
        "type_mix": dict(type_mix),
        "best_category": best,
        "worst_category": worst,
    }


def _recommended_posts_raw(dbp: str, today_iso: str) -> int:
    """Median posts/day over ACTIVE days in the 14 IST days ending the day before
    ``today_iso`` — independently mirrors ai/context.py:posting_trajectory."""
    today = date_cls.fromisoformat(today_iso)
    end_day = today - timedelta(days=1)
    first_day = end_day - timedelta(days=13)
    start_utc, end_utc = ist_range_to_sqlite_utc(first_day.isoformat(), end_day.isoformat())

    con = sqlite3.connect(dbp)
    cur = con.cursor()
    cur.execute(
        "SELECT posted_at FROM posts WHERE posted_at >= ? AND posted_at < ?",
        (start_utc, end_utc),
    )
    rows = cur.fetchall()
    con.close()

    IST = timedelta(hours=5, minutes=30)
    counts: Counter = Counter()
    for (posted_at,) in rows:
        ts = datetime.fromisoformat(posted_at.replace(" ", "T")).replace(tzinfo=timezone.utc)
        ist_date = (ts + IST).date()
        counts[ist_date] += 1

    active = [n for n in counts.values() if n > 0]
    return int(round(median(active))) if active else 0


def _content_concentration_raw(dbp: str, today_iso: str) -> dict | None:
    """Majority single/loot share over the trailing 45 days ending ``today_iso`` —
    independently mirrors campaign.py:_recent_distribution + _risks."""
    today = date_cls.fromisoformat(today_iso)
    start_day = today - timedelta(days=45)
    start_utc, end_utc = ist_range_to_sqlite_utc(start_day.isoformat(), today.isoformat())

    con = sqlite3.connect(dbp)
    cur = con.cursor()
    cur.execute(
        """
        SELECT np.is_multi_deal FROM posts p
        JOIN normalized_posts np ON np.source_id = p.id AND np.source_type = 'owned'
        WHERE p.posted_at >= ? AND p.posted_at < ?
        """,
        (start_utc, end_utc),
    )
    rows = cur.fetchall()
    con.close()

    post_types = Counter("loot_deal" if multi else "single_deal" for (multi,) in rows)
    total = sum(post_types.values())
    if total < 10:
        return None
    top_pt, top_pc = post_types.most_common(1)[0]
    share = top_pc / total
    if share <= 0.6:
        return None
    label = "loot / multi-deal posts" if top_pt == "loot_deal" else "single deal posts"
    return {"label": label, "pct": round(100 * share)}


def audit(today_iso: str) -> bool:
    from src.controllers.service import daily_brief

    api = daily_brief(date=today_iso)
    if not api.get("available"):
        print(f"API returned available=False: {api.get('reason')}")
        return False

    dbp = db_path()
    ok = True

    print(f"Audit target: today={today_iso} (IST), yesterday={api['prev_date']}\n")

    print("-- Yesterday card --")
    y_api = api.get("yesterday") or {}
    y_raw = _yesterday_raw(dbp, api["prev_date"])
    fields = ["posts_count", "views_avg", "engagement_rate", "best_category", "worst_category"]
    print(f"{'field':<18}{'dashboard':>16}{'raw-sql':>16}  status")
    for f in fields:
        av, rv = y_api.get(f), y_raw.get(f)
        match = av == rv
        ok = ok and match
        print(f"{f:<18}{str(av):>16}{str(rv):>16}  {'OK' if match else 'MISMATCH <<<'}")
    tm_match = (y_api.get("type_mix") or {}) == y_raw["type_mix"]
    ok = ok and tm_match
    print(f"{'type_mix':<18}{str(y_api.get('type_mix')):>16}{str(y_raw['type_mix']):>16}  {'OK' if tm_match else 'MISMATCH <<<'}")

    print("\n-- Today's recommended_posts --")
    rp_api = (api.get("today") or {}).get("recommended_posts")
    rp_raw = _recommended_posts_raw(dbp, today_iso)
    # only comparable when the AI/clamp path didn't override the deterministic
    # cadence — a plan_clamped=True or an AI-authored cadence_why means rp_api
    # legitimately differs from the raw median; flag that instead of a false MISMATCH.
    clamped = (api.get("today") or {}).get("plan_clamped")
    if clamped:
        print(f"dashboard={rp_api}  raw-median={rp_raw}  (plan_clamped=True — AI value clamped, not a direct median echo, skipping strict compare)")
    else:
        match = rp_api == rp_raw
        ok = ok and match
        print(f"dashboard={rp_api}  raw-median={rp_raw}  {'OK' if match else 'MISMATCH <<<'}")

    print("\n-- content_concentration risk banner --")
    risks_api = [r for r in ((api.get("today") or {}).get("risks") or []) if r.get("kind") == "content_concentration"]
    cc_raw = _content_concentration_raw(dbp, today_iso)
    if not risks_api and cc_raw is None:
        print("no banner shown, none expected  OK")
    elif risks_api and cc_raw is not None:
        detail = risks_api[0]["detail"]
        expect_pct = cc_raw["pct"]
        match = f"{expect_pct}%" in detail and cc_raw["label"] in detail
        ok = ok and match
        print(f"dashboard={detail!r}")
        print(f"raw-sql: {cc_raw['label']} is {expect_pct}% of last-45-day posts  {'OK' if match else 'MISMATCH <<<'}")
    else:
        ok = False
        print(f"MISMATCH <<< dashboard shown={bool(risks_api)} raw expected={cc_raw is not None}")

    print()
    print("PASS: every checked number matches an independent raw-SQL recomputation." if ok
          else "FAIL: at least one plan number does NOT match raw data.")
    print("\n(posting_windows/deal_type_allocation/merchant scoring and the AI narrative "
          "are out of scope for this script — see its module docstring for why.)")
    return ok


def _selfcheck() -> None:
    IST = timedelta(hours=5, minutes=30)
    assert (datetime(2026, 7, 24, 0, 0, tzinfo=timezone.utc) + IST).date() == date_cls(2026, 7, 24)
    counts = Counter({date_cls(2026, 7, 1): 5, date_cls(2026, 7, 2): 3, date_cls(2026, 7, 3): 7})
    active = [n for n in counts.values() if n > 0]
    assert int(round(median(active))) == 5, active
    print("selfcheck OK")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="IST date YYYY-MM-DD to audit as 'today' (checks the day before as 'yesterday')")
    p.add_argument("--selfcheck", action="store_true")
    args = p.parse_args()

    if args.selfcheck:
        _selfcheck()
        sys.exit(0)

    if not args.date:
        print("Pass --date (the IST date you're viewing on /plan).")
        sys.exit(2)

    sys.exit(0 if audit(args.date) else 1)
