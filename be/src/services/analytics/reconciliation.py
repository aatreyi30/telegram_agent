"""Closed-loop feedback (rescue plan §3.5).
adherence  = deterministic: planned slots vs actually-published posts (FACT).
attribution = correlational: expected_outcome vs actual report (NOT causal)."""
from __future__ import annotations


def _hour_of(window_ist: str) -> int | None:
    try:
        return int(window_ist.split(":")[0])
    except (ValueError, AttributeError, IndexError):
        return None


def compute_adherence(plan_slots: list[dict], published: list[dict]) -> dict:
    planned = len(plan_slots or [])
    pub = list(published or [])
    pub_hours = [p.get("hour_ist") for p in pub]
    matched = 0
    missed_windows: list[str] = []
    remaining = list(pub_hours)
    for slot in plan_slots or []:
        h = _hour_of(slot.get("window_ist", ""))
        # a slot is matched if a post published within +/-1h of its window start
        hit = next((ph for ph in remaining if ph is not None and h is not None and abs(ph - h) <= 1), None)
        if hit is not None:
            matched += 1
            remaining.remove(hit)
        else:
            missed_windows.append(slot.get("window_ist", "?"))

    def _bytype(items, key):
        out: dict[str, int] = {}
        for it in items:
            t = it.get("type", "?")
            out[t] = out.get(t, 0) + 1
        return out

    return {
        "planned": planned,
        "published": len(pub),
        "matched": matched,
        "missed_windows": missed_windows,
        "by_type": {"planned": _bytype(plan_slots or [], "type"), "published": _bytype(pub, "type")},
    }


def compute_attribution(expected_outcome: dict, report: dict) -> dict:
    """Diff each expected metric against the actual report value where a matching
    key exists. Correlational only — never asserts the plan caused the outcome."""
    items = []
    for key, exp in (expected_outcome or {}).items():
        if not isinstance(exp, (int, float)) or isinstance(exp, bool):
            continue
        act = report.get(key)
        items.append({
            "metric": key,
            "expected": exp,
            "actual": act if isinstance(act, (int, float)) else None,
            "gap": (act - exp) if isinstance(act, (int, float)) else None,
        })
    return {"items": items, "correlational": True,
            "caveat": "Correlation only; engagement is multi-causal — the plan did not necessarily cause these outcomes."}


def build_reconciliation(s, plan_date):
    """Load yesterday's AI plan + that day's owned report + published posts,
    compute adherence + attribution, store onto the plan.reconciliation column."""
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import select
    from src.db.models_campaign import CampaignPlan, PlanType
    from src.db.models_report import DailyChannelReport, ReportSourceType
    from src.services.analytics.periods import IST

    plan = s.scalars(
        select(CampaignPlan)
        .where(CampaignPlan.plan_type == PlanType.DAILY,
               CampaignPlan.target_date == plan_date,
               CampaignPlan.is_ai_generated == True)  # noqa: E712
        .order_by(CampaignPlan.generated_at.desc())
    ).first()
    if plan is None:
        return None
    report = s.scalars(
        select(DailyChannelReport).where(
            DailyChannelReport.report_date == plan_date,
            DailyChannelReport.source_type == ReportSourceType.OWNED,
        )
    ).first()
    report_d = {}
    if report is not None:
        report_d = {c: getattr(report, c) for c in report.__table__.columns.keys()}

    # published posts for the date (best-effort; fields verified against GeneratedPost)
    published: list[dict] = []
    try:
        from src.db.models_generation import GeneratedPost, PostStatus
        start = datetime(plan_date.year, plan_date.month, plan_date.day, tzinfo=IST).astimezone(timezone.utc)
        end = start + timedelta(days=1)
        rows = s.scalars(
            select(GeneratedPost).where(
                GeneratedPost.status == PostStatus.PUBLISHED,
                GeneratedPost.created_at >= start, GeneratedPost.created_at < end,
            )
        )
        for gp in rows:
            when = getattr(gp, "published_at", None) or gp.created_at
            published.append({"type": getattr(gp, "post_type", "?"),
                              "hour_ist": when.astimezone(IST).hour if when else None})
    except Exception:
        pass

    slots = (plan.blueprint or {}).get("post_slots", [])
    recon = {
        "adherence": compute_adherence(slots, published),
        "attribution": compute_attribution(plan.expected_outcome or {}, report_d),
        "caveat": "Adherence is fact; attribution is correlational, not causal.",
    }
    plan.adherence = recon["adherence"]
    plan.reconciliation = recon
    s.flush()
    return recon
