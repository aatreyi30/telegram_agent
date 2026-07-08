"""Glue: AI plan -> CampaignPlan row -> deterministic scheduling of real deals.
The AI decides strategy (slots); the deterministic planner fills them from real
inventory. Numbers are fact-checked before the plan is trusted."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from src.db.models_campaign import CampaignPlan, PlanType


def _parse_date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except (ValueError, TypeError):
        return None


def persist_ai_plan(s: Session, result: dict) -> CampaignPlan | None:
    if not result.get("available") or not result.get("plan"):
        return None
    plan = result["plan"]
    fc = result.get("factcheck", {"status": "skipped"})
    row = CampaignPlan(
        plan_type=PlanType.DAILY,
        title=f"AI day plan {plan.get('date') or ''}".strip(),
        target_date=_parse_date(plan.get("date")),
        blueprint=plan,
        expected_outcome={"emphasis": plan.get("emphasis"), "watch": plan.get("watch")},
        confidence=0.6 if fc.get("status") == "passed" else 0.3,
        generated_at=datetime.now(timezone.utc),
        is_ai_generated=True,
        ai_digest=result.get("digest", ""),
        cited_numbers=plan.get("cited_numbers", []),
        factcheck_status=fc.get("status", "skipped"),
        report_ids=result.get("report_ids", []),
    )
    s.add(row)
    s.flush()
    return row


def run_ai_daily(s: Session) -> dict:
    from src.ai.planner import generate_day_plan
    from src.ai.factcheck import check_cited_numbers
    from src.ai.context import daily_reports

    result = generate_day_plan(s)
    if not result.get("available"):
        return {"ok": False, "reason": result.get("reason", "ai unavailable")}
    # Fact-check against the exact facts the model was given (yesterday + trajectory),
    # falling back to persisted reports if present.
    facts = result.get("facts") or daily_reports(s, days=8)
    fc = check_cited_numbers(result["plan"].get("cited_numbers", []), facts)
    result["factcheck"] = fc
    plan_row = persist_ai_plan(s, result)

    scheduled = None
    if fc["status"] == "passed":
        try:
            from src.services.generation.daily_planner import build_and_schedule_day
            scheduled = build_and_schedule_day(s)
        except Exception as e:
            scheduled = {"ok": False, "reason": str(e)}
    return {
        "ok": True,
        "plan_id": plan_row.id if plan_row else None,
        "factcheck": fc,
        "scheduled": scheduled,
    }
