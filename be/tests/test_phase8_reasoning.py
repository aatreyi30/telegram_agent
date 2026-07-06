"""Phase 8 tests — trend windowing + shift/attribution logic (no DB/network)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.services.intelligence.reasoning import ReasoningEngine, _pct_change
from src.services.metrics import trend_metrics as T
from src.services.metrics.trend_metrics import TrendFact

NOW = datetime(2026, 7, 3, tzinfo=timezone.utc)


def _f(days_ago, views=None, cluster=None, has_cta=False, has_media=False):
    return TrendFact(
        posted_at=NOW - timedelta(days=days_ago), views=views, cluster=cluster,
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
    # recent heavy on 'hot'; prior heavy on 'cold'
    recent = [_f(5, cluster="hot") for _ in range(40)]
    prior = [_f(40, cluster="cold") for _ in range(40)]
    perf = {"hot": 200.0, "cold": 20.0}
    insights = []
    e._mix_shift(recent, prior, perf, perf_median=100.0, insights=insights)
    kinds = {i["evidence"]["cluster"]: i for i in insights}
    assert "hot" in kinds and kinds["hot"]["direction"] == "up"
    # plain-language reasoning that references the real numbers, no jargon
    r = kinds["hot"]["reasoning"].lower()
    assert "views a day" in r and "200" in r
    assert "pp" not in r and "median" not in r
