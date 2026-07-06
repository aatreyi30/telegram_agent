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
