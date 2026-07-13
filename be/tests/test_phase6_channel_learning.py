"""Phase 6 tests — learning computations (deterministic, no DB/network)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.services.learning.channel_learning import ChannelLearningEngine, Fact, _conf

NOW = datetime(2026, 7, 3, tzinfo=timezone.utc)


def _fact(views, cluster, has_cta=False, emojis=None, days_ago=10) -> Fact:
    return Fact(
        posted_at=NOW - timedelta(days=days_ago), views=views, forwards=1, reactions=None,
        text_len=100, num_links=1, has_coupon=False, is_multi_deal=False,
        has_cta=has_cta, has_media=False, emojis=emojis or [], hashtags=[],
        cluster=cluster, merchant_key=None,
    )


def test_views_per_day_age_normalization():
    f = _fact(views=100, cluster="x", days_ago=10)
    assert abs(f.views_per_day(NOW) - 10.0) < 1e-6   # 100 views / 10 days
    assert Fact(NOW, None, None, None, 0, 0, False, False, False, False, [], [], None, None).views_per_day(NOW) is None


def test_view_rate_prefers_24h_velocity_over_cumulative_proxy():
    # old post: huge cumulative views (100/day proxy) but a modest first-24h velocity
    old = _fact(views=3000, cluster="x", days_ago=30)   # proxy = 3000/30 = 100/day
    old.views_24h = 50
    assert old.view_rate(NOW) == 50.0                   # velocity wins, not the proxy

    # recent fast-starter: proxy understates it; velocity captures the burst
    new = _fact(views=200, cluster="x", days_ago=1)     # proxy = 200/day
    new.views_24h = 400
    assert new.view_rate(NOW) == 400.0

    # no snapshot captured yet -> honest fallback to the cumulative proxy
    bare = _fact(views=1000, cluster="x", days_ago=10)  # proxy = 100/day
    assert bare.views_24h is None
    assert abs(bare.view_rate(NOW) - 100.0) < 1e-6


def test_velocity_reorders_ranking_vs_cumulative():
    # By cumulative proxy 'slow' (200/day) would beat 'fast' (100/day); by true
    # first-24h velocity 'fast' (300) beats 'slow' (40), so ranking must flip.
    engine = ChannelLearningEngine()
    fast = []
    for _ in range(25):
        f = _fact(views=100, cluster="fast", days_ago=1)   # proxy 100/day
        f.views_24h = 300
        fast.append(f)
    slow = []
    for _ in range(25):
        f = _fact(views=6000, cluster="slow", days_ago=30)  # proxy 200/day
        f.views_24h = 40
        slow.append(f)
    perf = engine._post_type_performance(fast + slow, NOW)
    assert perf[0]["post_type"] == "fast"
    assert perf[0]["rank_by_views_per_day"] == 1


def test_confidence_scales_with_sample():
    assert _conf(0) == 0.0
    assert _conf(25) == 0.5
    assert _conf(100) == 1.0   # capped


def test_post_type_ranking_by_age_normalized_views():
    engine = ChannelLearningEngine()
    facts = [_fact(200, "hot") for _ in range(25)] + [_fact(20, "cold") for _ in range(25)]
    perf = engine._post_type_performance(facts, NOW)
    assert perf[0]["post_type"] == "hot"      # higher views/day ranks first
    assert perf[0]["rank_by_views_per_day"] == 1
    assert perf[-1]["post_type"] == "cold"


def test_learning_records_gated_by_sample_and_have_evidence():
    engine = ChannelLearningEngine()
    # CTA group has enough samples and clearly higher views
    facts = (
        [_fact(300, "a", has_cta=True) for _ in range(25)]
        + [_fact(100, "a", has_cta=False) for _ in range(25)]
    )
    recs = engine._learning_records(facts, NOW)
    cta = [r for r in recs if r["category"] == "cta"]
    assert cta, "CTA learning should be emitted when both groups >= sample threshold"
    assert cta[0]["sample_size"] >= 20
    assert cta[0]["evidence"] is not None
    assert cta[0]["comparison_value"] is not None  # baseline attached


def test_small_subgroups_are_withheld():
    engine = ChannelLearningEngine()
    # only 5 posts with CTA -> below MIN_GROUP_SAMPLE -> no CTA learning
    facts = [_fact(300, "a", has_cta=True) for _ in range(5)] + [_fact(100, "a") for _ in range(25)]
    recs = engine._learning_records(facts, NOW)
    assert not [r for r in recs if r["category"] == "cta"]
