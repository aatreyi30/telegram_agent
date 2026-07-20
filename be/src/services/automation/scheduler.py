"""The posting scheduler — processes due queue items.

Responsibilities (source_truth/04 Phase 11):
  * fire scheduled posts when their time arrives (multi-channel);
  * retry transient failures with exponential backoff, cap attempts;
  * treat permanent failures (no post rights, missing integration) as BLOCKED,
    never retried — recorded honestly, not faked;
  * pace sends to respect Telegram's ~1 msg/sec/chat limit.

The actual delivery is delegated to the gated Publisher (generation/publishing.py),
so on our member (non-admin) account every send correctly resolves to BLOCKED.
``process_due`` accepts an injectable ``publish_fn`` so the retry/blocked/publish
state machine is unit-testable without any network.
"""

from __future__ import annotations

import time as _time
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from src.db.models_automation import ScheduledPost, ScheduleStatus
from src.db.models_generation import PostStatus
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.logger import get_logger

logger = get_logger(__name__)

# permanent-failure signals in a publish note -> BLOCKED, do not retry
_PERMANENT_STATUSES = {PostStatus.BLOCKED}


def backoff_seconds(attempts: int) -> int:
    """Exponential backoff, capped at 1 hour: 60, 120, 240, ... <= 3600."""
    return min(60 * (2 ** max(0, attempts - 1)), 3600)


def _default_publish_fn(post_id: int, channel_ref: str) -> dict:
    from src.services.generation.publishing import Publisher
    return Publisher().publish(post_id, channel_ref, confirm=True)


class PostingScheduler:
    def __init__(self, poll_interval_seconds: int = 30, send_pacing_seconds: float = 1.1):
        self.poll_interval_seconds = poll_interval_seconds
        self.send_pacing_seconds = send_pacing_seconds
        self.bus = get_event_bus()

    # ------------------------------------------------------------------ #
    def _due_ids(self, now: datetime) -> list[int]:
        with session_scope() as s:
            rows = s.scalars(
                select(ScheduledPost.id).where(
                    or_(
                        (ScheduledPost.status == ScheduleStatus.QUEUED)
                        & (ScheduledPost.scheduled_at <= now),
                        (ScheduledPost.status == ScheduleStatus.RETRY)
                        & (ScheduledPost.next_attempt_at <= now),
                    )
                ).order_by(ScheduledPost.scheduled_at)
            ).all()
            return list(rows)

    def process_due(self, now: datetime | None = None, publish_fn=None,
                    pacing_seconds: float | None = None) -> dict:
        """Process every due item once. Returns a stats dict."""
        now = now or datetime.now(timezone.utc)
        publish_fn = publish_fn or _default_publish_fn
        pacing = self.send_pacing_seconds if pacing_seconds is None else pacing_seconds
        stats = {"due": 0, "published": 0, "blocked": 0, "retried": 0, "failed": 0, "errors": 0}

        due_ids = self._due_ids(now)
        stats["due"] = len(due_ids)
        for i, sid in enumerate(due_ids):
            # 1) claim: mark SENDING
            with session_scope() as s:
                row = s.get(ScheduledPost, sid)
                if row is None or row.status not in (ScheduleStatus.QUEUED, ScheduleStatus.RETRY):
                    continue
                gp_id, channel = row.generated_post_id, row.channel_ref
                row.status = ScheduleStatus.SENDING

            # 2) attempt the (gated) send OUTSIDE the DB session
            result, exc = None, None
            try:
                result = publish_fn(gp_id, channel)
            except Exception as e:  # transient (network, telethon, etc.)
                exc = e

            # 3) record outcome; collect an event to emit AFTER commit
            event = None
            with session_scope() as s:
                row = s.get(ScheduledPost, sid)
                if row is None:
                    continue
                row.attempts += 1
                if exc is not None:
                    row.last_error = f"{type(exc).__name__}: {exc}"
                    if row.attempts >= row.max_attempts:
                        row.status = ScheduleStatus.FAILED
                        stats["failed"] += 1
                        event = (EventType.POST_SEND_FAILED, {"error": row.last_error,
                                                              "attempts": row.attempts})
                    else:
                        row.status = ScheduleStatus.RETRY
                        row.next_attempt_at = now + timedelta(seconds=backoff_seconds(row.attempts))
                        stats["retried"] += 1
                        event = (EventType.POST_SEND_FAILED, {"error": row.last_error,
                                                              "retry_at": row.next_attempt_at.isoformat()})
                    stats["errors"] += 1
                else:
                    ok = bool(result and result.get("ok"))
                    status = (result or {}).get("status")
                    row.last_error = (result or {}).get("note")
                    if ok and status == PostStatus.PUBLISHED:
                        row.status = ScheduleStatus.PUBLISHED
                        row.published_at = now
                        stats["published"] += 1
                        event = (EventType.POST_SEND_ATTEMPTED, {"channel": channel, "result": "published"})
                    elif status in _PERMANENT_STATUSES:
                        # permanent: no rights / integration missing -> don't retry
                        row.status = ScheduleStatus.BLOCKED
                        stats["blocked"] += 1
                        event = (EventType.POST_SEND_BLOCKED, {"channel": channel,
                                                               "note": row.last_error})
                    else:
                        # unexpected non-ok without a permanent signal -> retry
                        if row.attempts >= row.max_attempts:
                            row.status = ScheduleStatus.FAILED
                            stats["failed"] += 1
                        else:
                            row.status = ScheduleStatus.RETRY
                            row.next_attempt_at = now + timedelta(seconds=backoff_seconds(row.attempts))
                            stats["retried"] += 1
                        event = (EventType.POST_SEND_FAILED, {"note": row.last_error})

            if event is not None:
                etype, data = event
                self.bus.publish(Event(event_type=etype, entity_type="scheduled_post",
                                       entity_id=str(sid), data=data))

            # 4) pace sends (Telegram ~1 msg/sec/chat); skip after the last item
            if pacing and i < len(due_ids) - 1:
                _time.sleep(pacing)

        logger.info("[automation] processed %(due)d due: %(published)d published, "
                    "%(blocked)d blocked, %(retried)d retry, %(failed)d failed", stats)
        return stats
