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


# Absolute daily post ceiling used ONLY on cold start (no posting history to derive a
# data-driven clamp). ~1 post/hour is a safe upper bound for a brand-new channel.
_COLD_START_MAX_POSTS = 24


def _rescale_slot_counts(plan: dict, target_total: int) -> None:
    """G10 — proportionally rescale ``post_slots``' ``count`` fields (in place) so
    they sum to ``target_total`` instead of whatever the model proposed. jit_fill
    reads ``post_slots`` directly to decide how many posts to actually make, so
    without this the clamp only ever changed the DISPLAYED recommended_posts —
    the executed plan stayed at the model's raw (unclamped) count."""
    slots = plan.get("post_slots") or []
    raw_total = sum(max(int(sl.get("count") or 0), 0) for sl in slots)
    if not slots or raw_total <= 0 or raw_total == target_total:
        return
    scaled = [max(round((sl.get("count") or 0) * target_total / raw_total), 0) for sl in slots]
    if target_total > 0 and sum(scaled) == 0:
        scaled[0] = 1
    drift = target_total - sum(scaled)
    if drift:
        i = max(range(len(scaled)), key=lambda k: scaled[k])
        scaled[i] = max(scaled[i] + drift, 0)
    for sl, c in zip(slots, scaled):
        sl["count"] = c


def persist_ai_plan(
    s: Session, result: dict,
    recent_median: int | None = None, recent_max_30d: int | None = None,
) -> CampaignPlan | None:
    """``recent_median``/``recent_max_30d`` are the same clamp bounds
    ``daily_brief`` uses for DISPLAY (``ctx.clamp_recommended_posts``) — passing
    them here applies that clamp at PERSIST time too (G10), so the stored
    blueprint jit_fill executes matches what's shown instead of drifting from it."""
    if not result.get("available") or not result.get("plan"):
        return None
    plan = result["plan"]
    rec = plan.get("recommended_posts")
    if rec is not None:
        if recent_median is not None:
            from src.ai.context import clamp_recommended_posts
            clamped, was_clamped = clamp_recommended_posts(rec, recent_median, recent_max_30d)
            # Record the outcome IN the blueprint so daily_brief (and cache-hit reads)
            # can surface "we clipped the AI's number" without re-deriving it from the
            # already-clamped value — re-clamping a clamped number always looks in-range.
            plan["plan_clamped"] = was_clamped
            if was_clamped:
                plan["recommended_posts"] = rec = clamped
        elif rec > _COLD_START_MAX_POSTS:
            # Cold start (no history -> no data-driven clamp bounds). The clamp used to be
            # skipped entirely here, so the model's raw count (e.g. 71) persisted AND
            # executed. Apply an absolute safety ceiling instead of trusting it blindly.
            # ponytail: fixed cold-start cap; superseded by the data-driven clamp the
            # moment any posting history exists.
            plan["recommended_posts"] = rec = _COLD_START_MAX_POSTS
            plan["plan_clamped"] = True
        # Reconcile slot counts to the final recommended_posts ALWAYS (every path, incl.
        # cold start): the model routinely lets post_slots' counts drift from its own
        # stated recommended_posts, and jit_fill executes the slot counts — so without
        # this the day would post the drifted total (e.g. 71) instead of the cadence.
        _rescale_slot_counts(plan, rec)
    fc = result.get("factcheck", {"status": "skipped"})
    target_date = _parse_date(plan.get("date"))
    row = CampaignPlan(
        plan_type=PlanType.DAILY,
        title=f"AI day plan {plan.get('date') or ''}".strip(),
        target_date=target_date,
        blueprint=plan,
        expected_outcome={"emphasis": plan.get("emphasis"), "watch": plan.get("watch")},
        confidence={"passed": 0.6, "warn": 0.45, "fallback": 0.2}.get(fc.get("status"), 0.3),
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
    only ever UPDATE a row that already existed, never make one).

    ``blueprint`` is expected to already carry the AI's parsed ``loot_deal_ratio``/
    ``merchant_priorities``/``daily_themes`` merged in (G1) — the caller
    (``_weekly_ai_generate``) does that merge, since it's the one place both the
    deterministic skeleton and the AI's parsed plan are in scope together."""
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
        # A row for this (week, is_ai_generated) already exists. UPDATE it in place with
        # the fresh blueprint/digest instead of returning the STALE one — otherwise a
        # re-run (or a concurrent request) silently dropped the AI's loot_ratio/
        # merchant_priorities/daily_themes and the daily planner read Nones (data_flow G1).
        logger.info(
            "[ai_execution] weekly plan row exists for week_start=%s — updating in place "
            "with the fresh blueprint", week_start,
        )
        existing = s.scalars(
            select(CampaignPlan)
            .where(CampaignPlan.campaign_version == CAMPAIGN_VERSION,
                   CampaignPlan.plan_type == PlanType.WEEKLY,
                   CampaignPlan.target_date == week_start,
                   CampaignPlan.is_ai_generated == is_ai_generated)
            .order_by(CampaignPlan.generated_at.desc())
        ).first()
        if existing is not None:
            existing.blueprint = blueprint
            existing.end_date = week_end
            existing.confidence = 0.6
            existing.generated_at = datetime.now(timezone.utc)
            if digest:
                existing.ai_digest = digest
            s.flush()
        return existing
