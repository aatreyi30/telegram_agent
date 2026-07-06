"""The posting queue — enqueue and auto-schedule drafts.

Two entry points:
  * ``enqueue`` — put one draft on the queue for one channel at one time.
    Idempotent: the same (draft, channel) pair is never queued twice while a
    live copy exists.
  * ``autoschedule`` — spread the most recent drafts across the *learned*
    posting windows from the current daily campaign plan. This connects
    Phase 10 (the plan) to Phase 11 (execution) using real, evidence-backed
    timing — not a hardcoded schedule.

Times are interpreted in IST (Asia/Kolkata, fixed +05:30 — India has no DST)
because the channel is Indian and the plan's window hours derive from
IST-posted content; they are stored as UTC.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models_automation import ScheduledPost, ScheduleStatus
from src.db.models_campaign import CampaignPlan, PlanType
from src.db.models_generation import GeneratedPost, PostStatus

IST = timezone(timedelta(hours=5, minutes=30))

# statuses that mean "a live queue entry already exists for this pair"
_LIVE = {ScheduleStatus.QUEUED, ScheduleStatus.RETRY,
         ScheduleStatus.SENDING, ScheduleStatus.PUBLISHED}


def _key(generated_post_id: int, channel_ref: str) -> str:
    return f"{generated_post_id}:{channel_ref.lstrip('@').lower()}"


def enqueue(
    session: Session,
    generated_post_id: int,
    channel_ref: str,
    scheduled_at: datetime,
    max_attempts: int = 3,
) -> tuple[ScheduledPost | None, str]:
    """Queue one draft for one channel. Returns (row, status_message).

    ``row`` is None only when the draft does not exist. Idempotent: if a live
    entry for this (draft, channel) already exists it is returned unchanged.
    A previously cancelled/failed entry is revived and rescheduled.
    """
    post = session.get(GeneratedPost, generated_post_id)
    if post is None:
        return None, f"No generated post #{generated_post_id}."

    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)

    key = _key(generated_post_id, channel_ref)
    existing = session.scalar(select(ScheduledPost).where(ScheduledPost.idempotency_key == key))
    if existing is not None:
        if existing.status in _LIVE:
            return existing, (f"Already queued (#{existing.id}, status={existing.status}); "
                              "not duplicated.")
        # revive a cancelled/failed entry
        existing.status = ScheduleStatus.QUEUED
        existing.scheduled_at = scheduled_at
        existing.attempts = 0
        existing.next_attempt_at = None
        existing.last_error = None
        existing.published_at = None
        existing.max_attempts = max_attempts
        return existing, f"Re-queued #{existing.id} (was {existing.status})."

    row = ScheduledPost(
        generated_post_id=generated_post_id,
        channel_ref=channel_ref,
        scheduled_at=scheduled_at,
        idempotency_key=key,
        status=ScheduleStatus.QUEUED,
        max_attempts=max_attempts,
    )
    session.add(row)
    session.flush()
    return row, f"Queued #{row.id} for {channel_ref} at {scheduled_at.isoformat()}."


_HOUR_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _window_start_end(hours_label: str) -> tuple[int, int] | None:
    """Parse a window label like '18:00–23:00' -> (18, 23)."""
    found = _HOUR_RE.findall(hours_label or "")
    if len(found) < 2:
        return None
    start = int(found[0][0])
    end = int(found[1][0])
    return start, end


def plan_time_slots(windows: list[dict], base_day: date, per_window_cap: int | None = None) -> list[datetime]:
    """Build sorted UTC datetimes from a plan's posting windows.

    Each window contributes ``posts`` evenly-spaced slots across its hour span
    (IST), converted to UTC. ``per_window_cap`` optionally limits slots/window.
    """
    slots: list[datetime] = []
    for w in windows or []:
        se = _window_start_end(w.get("hours", ""))
        n = int(w.get("posts") or 0)
        if se is None or n <= 0:
            continue
        if per_window_cap:
            n = min(n, per_window_cap)
        start, end = se
        span = (end - start) if end > start else 1  # guard degenerate/one-hour spans
        for k in range(n):
            # spread within the span; first slot at start, avoid landing on `end`
            offset_h = start + (span * k / n)
            hh = int(offset_h) % 24
            mm = int(round((offset_h - int(offset_h)) * 60)) % 60
            ist_dt = datetime.combine(base_day, time(hh, mm), tzinfo=IST)
            slots.append(ist_dt.astimezone(timezone.utc))
    return sorted(slots)


def _recent_drafts(session: Session, count: int) -> list[GeneratedPost]:
    return list(session.scalars(
        select(GeneratedPost)
        .where(GeneratedPost.status == PostStatus.DRAFT)
        .order_by(GeneratedPost.generated_at.desc(), GeneratedPost.id.desc())
        .limit(count)
    ))


def autoschedule(
    session: Session,
    channel_ref: str,
    count: int,
    base_day: date | None = None,
    post_ids: list[int] | None = None,
) -> dict:
    """Spread drafts across the current daily plan's posting windows.

    Returns a report dict: which drafts landed at which times, and any that
    couldn't be placed. If no daily plan exists, returns a skip reason.
    """
    plan = session.scalar(
        select(CampaignPlan)
        .where(CampaignPlan.plan_type == PlanType.DAILY)
        .order_by(CampaignPlan.generated_at.desc())
    )
    if plan is None:
        return {"ok": False, "reason": "No daily campaign plan. Run `tgagent plan` first."}
    windows = (plan.blueprint or {}).get("posting_windows") or []
    if not windows:
        return {"ok": False, "reason": "Daily plan has no posting windows (need more posting-hour data)."}

    if post_ids:
        drafts = [session.get(GeneratedPost, pid) for pid in post_ids]
        drafts = [d for d in drafts if d is not None]
    else:
        drafts = _recent_drafts(session, count)
    if not drafts:
        return {"ok": False, "reason": "No draft posts to schedule. Run `tgagent generate-live` first."}

    base_day = base_day or datetime.now(timezone.utc).astimezone(IST).date()
    scheduled, skipped = [], []
    day_offset = 0
    slots = plan_time_slots(windows, base_day)
    slot_i = 0
    for draft in drafts:
        # spill to the next day when a day's slots are exhausted
        if slot_i >= len(slots):
            day_offset += 1
            slots = plan_time_slots(windows, base_day + timedelta(days=day_offset))
            slot_i = 0
            if not slots:
                skipped.append({"post_id": draft.id, "reason": "no slots"})
                continue
        when = slots[slot_i]
        slot_i += 1
        row, msg = enqueue(session, draft.id, channel_ref, when)
        if row is None:
            skipped.append({"post_id": draft.id, "reason": msg})
        else:
            scheduled.append({"scheduled_id": row.id, "post_id": draft.id,
                              "channel": channel_ref, "at_utc": when.isoformat(),
                              "at_ist": when.astimezone(IST).strftime("%Y-%m-%d %H:%M IST"),
                              "note": msg})
    return {"ok": True, "plan_id": plan.id, "windows": len(windows),
            "scheduled": scheduled, "skipped": skipped}
