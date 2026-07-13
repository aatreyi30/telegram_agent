"""Shared posting-window builder.

Distributes a daily posting budget across readable day-parts, weighting volume
toward higher-performing parts while keeping presence in every active part.

Extracted from the Growth engine so the campaign planner can reuse the exact
same logic for its history-derived fallback (used when the Growth blueprint has
no ``posting_plan`` yet — cold-start / before learning has run).
"""

from __future__ import annotations

# day-parts are time buckets for a readable schedule (not business categories)
DAY_PARTS = [
    ("Late night", "00:00–05:00", range(0, 6)),
    ("Morning", "06:00–11:00", range(6, 12)),
    ("Afternoon", "12:00–17:00", range(12, 18)),
    ("Evening", "18:00–23:00", range(18, 24)),
]


def build_posting_plan(posts_per_day, hourly_all) -> list[dict] | None:
    """Distribute the daily posting budget across day-parts, shifting volume
    toward higher-performing parts while keeping presence in every active part
    (you post many times/day — never collapse to a single hour)."""
    if not posts_per_day or not hourly_all:
        return None
    # hourly_all: [[hour, avg_views_per_day, n_posts], ...]
    by_hour = {int(h): (avg, n) for h, avg, n in hourly_all}
    total_n = sum(n for _, n in by_hour.values()) or 1
    overall_avg = sum(avg * n for avg, n in by_hour.values()) / total_n or 1.0

    parts = []
    for name, label, hours in DAY_PARTS:
        ns = [by_hour[h][1] for h in hours if h in by_hour]
        avgs = [by_hour[h] for h in hours if h in by_hour]
        part_n = sum(ns)
        if part_n == 0:
            continue
        part_avg = sum(a * n for a, n in avgs) / part_n
        current_share = part_n / total_n
        parts.append({
            "part": name, "hours": label, "current_share": current_share,
            "part_avg_views_per_day": part_avg, "sample_size": part_n,
            # weight current volume by relative performance -> shift toward winners
            "raw_weight": current_share * (part_avg / overall_avg),
        })
    if not parts:
        return None
    wsum = sum(p["raw_weight"] for p in parts) or 1.0
    plan = []
    for p in parts:
        rec_share = p["raw_weight"] / wsum
        cur_ppd = round(posts_per_day * p["current_share"], 1)
        rec_ppd = max(1, round(posts_per_day * rec_share))  # keep >=1: never zero a part
        action = ("increase" if rec_ppd > cur_ppd * 1.15
                  else "reduce" if rec_ppd < cur_ppd * 0.85 else "maintain")
        plan.append({
            "part": p["part"], "hours": p["hours"],
            "current_posts_per_day": cur_ppd,
            "recommended_posts_per_day": rec_ppd,
            "avg_views_per_day": round(p["part_avg_views_per_day"], 1),
            "sample_size": p["sample_size"],
            "action": action,
        })
    return plan
