"""Revert must restore the EXACT pre-steer WEEKLY plan from blueprint._pre_steer — same
contract as test_revert_daily.py, scoped to PlanType.WEEKLY (target_date = week_start)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from src.controllers import service
from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan, PlanType
from src.db.session import session_scope
from src.services.analytics.periods import ist_today


def _latest(s, week_start):
    return s.scalar(select(CampaignPlan).where(
        CampaignPlan.campaign_version == CAMPAIGN_VERSION,
        CampaignPlan.plan_type == PlanType.WEEKLY,
        CampaignPlan.target_date == week_start).order_by(CampaignPlan.generated_at.desc()))


def test_revert_weekly_restores_pre_steer_plan():
    week_end = ist_today()  # anchor within the current trailing window -> revert allowed
    week_start = week_end - timedelta(days=6)

    original_bp = {"direction": "ORIGINAL direction", "posts_per_day": 10,
                   "merchant_priorities": [{"merchant": "amazon"}]}
    pre_steer = {"title": "orig weekly plan", "blueprint": original_bp, "expected_outcome": None,
                 "confidence": 0.6, "is_ai_generated": True, "ai_digest": "ORIGINAL WEEKLY DIGEST",
                 "cited_numbers": [], "factcheck_status": "passed", "report_ids": [],
                 "operator_directive": None}
    steered_bp = {"direction": "STEERED direction", "posts_per_day": 20,
                  "merchant_priorities": [{"merchant": "flipkart"}], "_pre_steer": pre_steer}

    with session_scope() as s:
        s.execute(delete(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.WEEKLY,
            CampaignPlan.target_date == week_start))
        s.add(CampaignPlan(plan_type=PlanType.WEEKLY, campaign_version=CAMPAIGN_VERSION,
                           target_date=week_start, end_date=week_end,
                           generated_at=datetime.now(timezone.utc),
                           title="steered weekly plan", is_ai_generated=True, blueprint=steered_bp,
                           ai_digest="STEERED WEEKLY DIGEST", factcheck_status="passed",
                           cited_numbers=[], report_ids=[], operator_directive="lean loot"))

    result = service.revert_weekly(end=week_end.isoformat())
    assert result["available"] is True

    with session_scope() as s:
        row = _latest(s, week_start)
        assert row is not None, "no weekly plan row after revert"
        bp = row.blueprint or {}
        assert bp.get("direction") == "ORIGINAL direction", bp
        assert bp.get("posts_per_day") == 10, bp
        assert row.ai_digest == "ORIGINAL WEEKLY DIGEST", row.ai_digest
        # snapshot consumed -> can't re-revert (one level of undo)
        assert "_pre_steer" not in bp, "pre_steer not stripped"
        # cleanup
        s.execute(delete(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.WEEKLY,
            CampaignPlan.target_date == week_start))


def test_revert_weekly_refuses_when_never_steered():
    week_end = ist_today()
    week_start = week_end - timedelta(days=6)
    plain_bp = {"direction": "plain direction", "posts_per_day": 8}

    with session_scope() as s:
        s.execute(delete(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.WEEKLY,
            CampaignPlan.target_date == week_start))
        s.add(CampaignPlan(plan_type=PlanType.WEEKLY, campaign_version=CAMPAIGN_VERSION,
                           target_date=week_start, end_date=week_end,
                           generated_at=datetime.now(timezone.utc),
                           title="plain weekly plan", is_ai_generated=True, blueprint=plain_bp,
                           ai_digest="PLAIN DIGEST", factcheck_status="passed",
                           cited_numbers=[], report_ids=[], operator_directive=None))

    result = service.revert_weekly(end=week_end.isoformat())
    assert result["available"] is False
    assert "hasn't been steered" in result["reason"]

    with session_scope() as s:
        s.execute(delete(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.WEEKLY,
            CampaignPlan.target_date == week_start))


def test_revert_weekly_refuses_an_elapsed_week():
    result = service.revert_weekly(end="2020-01-06")
    assert result["available"] is False
    assert result["reason"] == "This week has already elapsed — reverting it has no effect."