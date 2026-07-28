"""A mid-day steer must rewrite only the REMAINING day — already-posted (past) slots
are immutable and stay exactly as they were; the fresh plan supplies only future slots."""
from __future__ import annotations

from src.controllers.service import _past_future_split, _splice_past_over

NOON = 12 * 60


def _s(t, tag=""):
    return {"time_ist": t, "merchant": tag or "amazon", "theme": "t", "type": "single"}


def test_split_by_now():
    slots = [_s("06:30"), _s("11:59"), _s("12:00"), _s("20:00")]
    past, future = _past_future_split(slots, NOON)
    assert [p["time_ist"] for p in past] == ["06:30", "11:59"]        # strictly before noon
    assert [f["time_ist"] for f in future] == ["12:00", "20:00"]      # noon onward is upcoming


def test_not_today_everything_upcoming():
    slots = [_s("06:30"), _s("20:00")]
    past, future = _past_future_split(slots, None)   # None => not today
    assert past == [] and len(future) == 2


def test_splice_keeps_past_takes_fresh_future():
    past = [_s("06:30", "OLD"), _s("09:15", "OLD")]           # already posted this morning
    fresh = [_s("07:00", "NEW"), _s("14:00", "NEW"), _s("20:30", "NEW")]  # a full fresh replan
    out = _splice_past_over(past, fresh, NOON)
    # the fresh MORNING slot (07:00) is discarded; past mornings preserved; fresh future kept
    assert [(x["time_ist"], x["merchant"]) for x in out] == [
        ("06:30", "OLD"), ("09:15", "OLD"), ("14:00", "NEW"), ("20:30", "NEW")]


def test_splice_chronological():
    past = [_s("10:00")]
    fresh = [_s("21:00"), _s("13:00"), _s("15:30")]
    out = _splice_past_over(past, fresh, NOON)
    assert [x["time_ist"] for x in out] == ["10:00", "13:00", "15:30", "21:00"]