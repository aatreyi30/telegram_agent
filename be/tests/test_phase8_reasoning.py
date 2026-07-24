"""Phase 8 tests — trend windowing + shift/attribution logic (no DB/network)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.services.intelligence.reasoning import ReasoningEngine, _pct_change
from src.services.metrics import trend_metrics as T
from src.services.metrics.trend_metrics import TrendFact

NOW = datetime(2026, 7, 3, tzinfo=timezone.utc)


def _f(days_ago, views=None, is_multi_deal=False, has_cta=False, has_media=False):
    return TrendFact(
        posted_at=NOW - timedelta(days=days_ago), views=views, is_multi_deal=is_multi_deal,
        merchant_key=None, has_cta=has_cta, has_media=has_media,
    )


def test_pct_change():
    assert _pct_change(120, 100) == 20.0
    assert _pct_change(50, 100) == -50.0
    assert _pct_change(10, 0) is None   # no baseline -> undefined, not fabricated


def test_posting_window_and_matured_window():
    facts = [_f(5), _f(20), _f(40), _f(75)]
    recent = T.in_posting_window(facts, NOW - timedelta(days=30), NOW)
    assert len(recent) == 2                       # 5 and 20 days ago
    matured = T.matured_window(facts, NOW, 30, 60)
    assert len(matured) == 1                       # only the 40-day-old post


def test_avg_views_per_day_age_normalizes():
    facts = [_f(10, views=100), _f(20, views=100)]  # 10/day and 5/day
    avg, n = T.avg_views_per_day(facts, NOW)
    assert n == 2
    assert abs(avg - 7.5) < 1e-6


def test_volume_shift_detected_and_measured():
    e = ReasoningEngine(window_days=30)
    recent = [_f(d % 30) for d in range(40)]        # 40 posts last 30d
    prior = [_f(30 + (d % 30)) for d in range(80)]  # 80 posts prior 30d
    insights = []
    e._volume_shift(recent, prior, 30, NOW, insights)
    assert insights and insights[0]["metric"] == "posting_volume"
    assert insights[0]["direction"] == "down"       # 40 < 80
    assert insights[0]["evidence"]["n_recent"] == 40


def test_mix_shift_attributes_to_performance():
    e = ReasoningEngine(window_days=30)
    # recent heavy on loot boards; prior heavy on single deals. The engine keys the
    # mix by is_multi_deal -> "loot_deal"/"single_deal" (post_type), not free clusters.
    recent = [_f(5, is_multi_deal=True) for _ in range(40)]
    prior = [_f(40, is_multi_deal=False) for _ in range(40)]
    perf = {"loot_deal": 200.0, "single_deal": 20.0}
    insights = []
    e._mix_shift(recent, prior, perf, perf_median=100.0, insights=insights)
    kinds = {i["evidence"]["post_type"]: i for i in insights}
    # Structural assertions are deterministic — the real contract of _mix_shift.
    assert "loot_deal" in kinds and kinds["loot_deal"]["direction"] == "up"
    assert kinds["loot_deal"]["evidence"]["post_type"] == "loot_deal"
    # `reasoning` is produced by a LIVE LLM call, so its exact wording varies run to run.
    # Assert only that plain-language reasoning is present, not its content — asserting on
    # generated text made this test flaky (it failed intermittently at baseline too).
    r = kinds["loot_deal"]["reasoning"]
    assert isinstance(r, str) and r.strip()
