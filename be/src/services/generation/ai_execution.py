"""Glue: AI plan -> CampaignPlan row -> deterministic scheduling of real deals.
The AI decides strategy (slots); the deterministic planner fills them from real
inventory. Numbers are fact-checked before the plan is trusted."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan, PlanType
from src.logger import get_logger

logger = get_logger(__name__)


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
    target_date = _parse_date(plan.get("date"))
    row = CampaignPlan(
        plan_type=PlanType.DAILY,
        title=f"AI day plan {plan.get('date') or ''}".strip(),
        target_date=target_date,
        blueprint=plan,
        expected_outcome={"emphasis": plan.get("emphasis"), "watch": plan.get("watch")},
        confidence={"passed": 0.6, "warn": 0.45}.get(fc.get("status"), 0.3),
        generated_at=datetime.now(timezone.utc),
        is_ai_generated=True,
        ai_digest=result.get("digest", ""),
        cited_numbers=plan.get("cited_numbers", []),
        factcheck_status=fc.get("status", "skipped"),
        report_ids=result.get("report_ids", []),
    )
    try:
        # SAVEPOINT: on a unique-constraint violation we only need to unwind this
        # insert, not the whole (mostly read-only) outer transaction the caller may
        # still be using (e.g. daily_brief() building the rest of its response).
        with s.begin_nested():
            s.add(row)
            s.flush()
        return row
    except IntegrityError:
        # Two near-simultaneous requests for the same day both missed the cache and
        # both tried to persist an AI plan — the unique index on (campaign_version,
        # plan_type, target_date, is_ai_generated) rejects the loser. Don't 500:
        # the winner's row already has everything we need, so use it instead.
        logger.info(
            "[ai_execution] concurrent AI plan insert lost the race for target_date=%s "
            "— reusing the row the other request just persisted", target_date,
        )
        existing = s.scalars(
            select(CampaignPlan)
            .where(CampaignPlan.campaign_version == CAMPAIGN_VERSION,
                   CampaignPlan.plan_type == PlanType.DAILY,
                   CampaignPlan.target_date == target_date,
                   CampaignPlan.is_ai_generated == True)  # noqa: E712
            .order_by(CampaignPlan.generated_at.desc())
        ).first()
        return existing


def persist_weekly_plan(
    s: Session, week_start: date, week_end: date, blueprint: dict,
    digest: str = "", is_ai_generated: bool = False,
) -> CampaignPlan | None:
    """Insert a fresh WEEKLY ``CampaignPlan`` row keyed by calendar week (Monday
    ``week_start``) — the create-path ``weekly_brief()`` was missing (it could
    only ever UPDATE a row that already existed, never make one)."""
    row = CampaignPlan(
        plan_type=PlanType.WEEKLY,
        title=f"Weekly plan — week of {week_start.isoformat()}",
        target_date=week_start,
        end_date=week_end,
        blueprint=blueprint,
        confidence=0.6,
        generated_at=datetime.now(timezone.utc),
        is_ai_generated=is_ai_generated,
        ai_digest=digest or None,
    )
    try:
        # Same SAVEPOINT pattern as persist_ai_plan: a losing insert only unwinds
        # itself, not the caller's outer (mostly read-only) transaction.
        with s.begin_nested():
            s.add(row)
            s.flush()
        return row
    except IntegrityError:
        logger.info(
            "[ai_execution] concurrent weekly plan insert lost the race for "
            "week_start=%s — reusing the row the other request just persisted", week_start,
        )
        existing = s.scalars(
            select(CampaignPlan)
            .where(CampaignPlan.campaign_version == CAMPAIGN_VERSION,
                   CampaignPlan.plan_type == PlanType.WEEKLY,
                   CampaignPlan.target_date == week_start,
                   CampaignPlan.is_ai_generated == is_ai_generated)
            .order_by(CampaignPlan.generated_at.desc())
        ).first()
        return existing
