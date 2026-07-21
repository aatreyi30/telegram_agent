"""Phase 11 tests — queue idempotency, window slotting, and the send state machine.

The state machine (process_due) is exercised with an INJECTED publish function,
so retry/blocked/publish transitions are verified with zero network.
"""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timedelta, timezone

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/auto.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db

    init_db()
    yield


# --------------------------- pure logic --------------------------- #
def test_backoff_is_exponential_and_capped():
    from src.services.automation.scheduler import backoff_seconds

    assert backoff_seconds(1) == 60
    assert backoff_seconds(2) == 120
    assert backoff_seconds(3) == 240
    assert backoff_seconds(99) == 3600      # capped at 1 hour


def test_window_parsing_and_slot_spread():
    from src.services.automation.queue import IST, plan_time_slots, _window_start_end

    assert _window_start_end("18:00–23:00") == (18, 23)
    assert _window_start_end("no digits") is None

    windows = [{"part": "Evening", "hours": "18:00–23:00", "posts": 2},
               {"part": "Morning", "hours": "06:00–11:00", "posts": 1}]
    slots = plan_time_slots(windows, date(2026, 7, 3))
    assert len(slots) == 3                    # 2 + 1
    # returned in UTC, sorted, and morning (06 IST) comes before evening (18 IST)
    ist = [s.astimezone(IST).hour for s in slots]
    assert ist == sorted(ist)
    assert ist[0] == 6                        # first morning slot at window start


# --------------------------- queue idempotency --------------------------- #
def _make_draft(text="hello"):
    from src.db.models_generation import GeneratedPost, PostStatus
    from src.db.session import session_scope

    with session_scope() as s:
        gp = GeneratedPost(generated_at=datetime.now(timezone.utc), post_type="single",
                           deal_ids=["d1"], rendered_text=text, status=PostStatus.DRAFT)
        s.add(gp)
        s.flush()
        return gp.id


def test_enqueue_is_idempotent_per_pair():
    from src.services.automation.queue import enqueue
    from src.db.session import session_scope

    pid = _make_draft()
    when = datetime.now(timezone.utc) + timedelta(minutes=5)
    with session_scope() as s:
        row1, msg1 = enqueue(s, pid, "@Chan", when)
        row2, msg2 = enqueue(s, pid, "@Chan", when + timedelta(hours=1))
    assert row1.id == row2.id                 # same pair -> not duplicated
    assert "not duplicated" in msg2
    # a different channel is a distinct queue entry
    with session_scope() as s:
        row3, _ = enqueue(s, pid, "@Other", when)
    assert row3.id != row1.id


def test_enqueue_missing_draft_returns_none():
    from src.services.automation.queue import enqueue
    from src.db.session import session_scope

    with session_scope() as s:
        row, msg = enqueue(s, 999999, "@Chan", datetime.now(timezone.utc))
    assert row is None and "No generated post" in msg


# --------------------------- send state machine --------------------------- #
def test_process_due_marks_blocked_permanently():
    from src.services.automation.queue import enqueue
    from src.services.automation.scheduler import PostingScheduler
    from src.db.models_automation import ScheduledPost, ScheduleStatus
    from src.db.models_generation import PostStatus
    from src.db.session import session_scope

    pid = _make_draft("blocked-case")
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    with session_scope() as s:
        row, _ = enqueue(s, pid, "@NoRights", past)
        sid = row.id

    # publisher says BLOCKED (permanent: no admin rights)
    def fake_publish(post_id, channel):
        return {"ok": False, "status": PostStatus.BLOCKED, "note": "no post rights"}

    stats = PostingScheduler().process_due(publish_fn=fake_publish, pacing_seconds=0)
    assert stats["blocked"] >= 1
    with session_scope() as s:
        row = s.get(ScheduledPost, sid)
    assert row.status == ScheduleStatus.BLOCKED
    assert row.attempts == 1                   # blocked = no retry


def test_reclaim_resets_stale_sending_but_leaves_fresh_alone():
    """A post stranded in SENDING (worker died mid-send) must be reclaimed to QUEUED so
    it isn't stuck past its fire time forever; a post that only just went SENDING must
    NOT be touched (it may still be delivering)."""
    from src.services.automation.queue import enqueue
    from src.services.automation.scheduler import PostingScheduler, _STALE_SENDING_MIN
    from src.db.models_automation import ScheduledPost, ScheduleStatus
    from src.db.session import session_scope

    now = datetime.now(timezone.utc)
    pid_stale = _make_draft("stale-send")   # create drafts OUTSIDE the session (own txn)
    pid_fresh = _make_draft("fresh-send")
    with session_scope() as s:
        stale, _ = enqueue(s, pid_stale, "@X", now - timedelta(minutes=_STALE_SENDING_MIN + 5))
        stale.status = ScheduleStatus.SENDING
        stale_id = stale.id
        fresh, _ = enqueue(s, pid_fresh, "@X", now - timedelta(minutes=1))
        fresh.status = ScheduleStatus.SENDING
        fresh_id = fresh.id

    n = PostingScheduler()._reclaim_stale_sending(now)
    assert n >= 1
    with session_scope() as s:
        assert s.get(ScheduledPost, stale_id).status == ScheduleStatus.QUEUED  # recovered
        assert s.get(ScheduledPost, fresh_id).status == ScheduleStatus.SENDING  # left alone


def test_process_due_retries_then_fails_on_transient_error():
    from src.services.automation.queue import enqueue
    from src.services.automation.scheduler import PostingScheduler
    from src.db.models_automation import ScheduledPost, ScheduleStatus
    from src.db.session import session_scope

    pid = _make_draft("transient-case")
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    with session_scope() as s:
        row, _ = enqueue(s, pid, "@Flaky", past, max_attempts=2)
        sid = row.id

    def boom(post_id, channel):
        raise ConnectionError("network down")

    sched = PostingScheduler()
    # attempt 1 -> transient -> RETRY (next_attempt in the past so it re-fires)
    sched.process_due(publish_fn=boom, pacing_seconds=0)
    with session_scope() as s:
        row = s.get(ScheduledPost, sid)
        assert row.status == ScheduleStatus.RETRY
        assert row.attempts == 1
        # force the retry to be due now
        row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    # attempt 2 -> hits max_attempts -> FAILED
    sched.process_due(publish_fn=boom, pacing_seconds=0)
    with session_scope() as s:
        row = s.get(ScheduledPost, sid)
    assert row.status == ScheduleStatus.FAILED
    assert row.attempts == 2


def test_process_due_publishes_on_success():
    from src.services.automation.queue import enqueue
    from src.services.automation.scheduler import PostingScheduler
    from src.db.models_automation import ScheduledPost, ScheduleStatus
    from src.db.models_generation import PostStatus
    from src.db.session import session_scope

    pid = _make_draft("ok-case")
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    with session_scope() as s:
        row, _ = enqueue(s, pid, "@Admin", past)
        sid = row.id

    def ok_publish(post_id, channel):
        return {"ok": True, "status": PostStatus.PUBLISHED, "note": "sent"}

    stats = PostingScheduler().process_due(publish_fn=ok_publish, pacing_seconds=0)
    assert stats["published"] >= 1
    with session_scope() as s:
        row = s.get(ScheduledPost, sid)
    assert row.status == ScheduleStatus.PUBLISHED
    assert row.published_at is not None


def test_not_yet_due_is_not_processed():
    from src.services.automation.queue import enqueue
    from src.services.automation.scheduler import PostingScheduler
    from src.db.models_automation import ScheduledPost, ScheduleStatus
    from src.db.models_generation import PostStatus
    from src.db.session import session_scope

    pid = _make_draft("future-case")
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    with session_scope() as s:
        row, _ = enqueue(s, pid, "@Later", future)
        sid = row.id

    def ok_publish(post_id, channel):
        return {"ok": True, "status": PostStatus.PUBLISHED, "note": "sent"}

    PostingScheduler().process_due(publish_fn=ok_publish, pacing_seconds=0)
    with session_scope() as s:
        row = s.get(ScheduledPost, sid)
    assert row.status == ScheduleStatus.QUEUED     # untouched
