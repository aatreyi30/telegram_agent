"""Revert must restore the EXACT pre-steer plan from blueprint._pre_steer — the steered
slots/digest are replaced by the originals, and the snapshot is consumed (no re-revert)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select

from src.controllers import service
from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan, PlanType
from src.db.session import session_scope
from src.services.analytics.periods import ist_today


def _latest(s, day):
    return s.scalar(select(CampaignPlan).where(
        CampaignPlan.campaign_version == CAMPAIGN_VERSION,
        CampaignPlan.plan_type == PlanType.DAILY,
        CampaignPlan.target_date == day).order_by(CampaignPlan.generated_at.desc()))


def test_revert_restores_pre_steer_plan():
    day = ist_today()  # today -> not elapsed, so revert is allowed
    original_bp = {"post_slots": [{"time_ist": "09:00", "type": "single",
                                   "merchant": "amazon", "why": "ORIGINAL"}],
                   "recommended_posts": 10, "emphasis": "orig"}
    pre_steer = {"title": "orig plan", "blueprint": original_bp, "expected_outcome": None,
                 "confidence": 0.6, "is_ai_generated": True, "ai_digest": "ORIGINAL DIGEST",
                 "cited_numbers": [], "factcheck_status": "passed", "report_ids": [],
                 "operator_directive": None}
    steered_bp = {"post_slots": [{"time_ist": "10:00", "type": "collection",
                                  "merchant": "flipkart", "why": "STEERED"}],
                  "recommended_posts": 5, "_pre_steer": pre_steer}

    with session_scope() as s:
        s.execute(delete(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.DAILY,
            CampaignPlan.target_date == day))
        s.add(CampaignPlan(plan_type=PlanType.DAILY, campaign_version=CAMPAIGN_VERSION,
                           target_date=day, generated_at=datetime.now(timezone.utc),
                           title="steered plan", is_ai_generated=True, blueprint=steered_bp,
                           ai_digest="STEERED DIGEST", factcheck_status="passed",
                           cited_numbers=[], report_ids=[], operator_directive="make it loot"))

    service.revert_daily(date=day.isoformat())

    with session_scope() as s:
        row = _latest(s, day)
        assert row is not None, "no plan row after revert"
        slots = (row.blueprint or {}).get("post_slots") or []
        assert slots and slots[0]["why"] == "ORIGINAL", f"slots not restored: {slots}"
        assert row.ai_digest == "ORIGINAL DIGEST", row.ai_digest
        # snapshot consumed -> can't re-revert (one level of undo)
        assert "_pre_steer" not in (row.blueprint or {}), "pre_steer not stripped"
        # cleanup
        s.execute(delete(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.DAILY,
            CampaignPlan.target_date == day))