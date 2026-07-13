"""Phase 3.2 tests -- DealScoringEngine: weighted formula sums to `score`,
fake-MRP discount cap, unknown-merchant/scarcity defaults, and out-of-range
guards on every component. Mirrors test_engagement_score.py's isolated-DB
module fixture + pure-function unit tests."""

from __future__ import annotations

import math
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/deal_scoring.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db

    init_db()
    yield


def _deal(**kw):
    from src.db.models_generation import EnrichedDeal

    defaults = dict(
        deal_id="d1", merchant_key="boat", discount_percent=30.0,
        current_price=1000.0, original_price=1400.0,
        url="https://boat.example/p1", clean_url="https://boat.example/p1",
    )
    defaults.update(kw)
    return EnrichedDeal(**defaults)


# --------------------------------------------------------------------------- #
# discount_depth -- pure, no DB
# --------------------------------------------------------------------------- #
def test_discount_depth_scales_linearly_and_caps_at_one():
    from src.services.intelligence.deal_scoring import discount_depth

    assert discount_depth(_deal(discount_percent=30.0), None) == pytest.approx(0.5)
    assert discount_depth(_deal(discount_percent=120.0), None) == pytest.approx(1.0)
    assert discount_depth(_deal(discount_percent=0.0), None) == pytest.approx(0.0)
    assert discount_depth(_deal(discount_percent=None), None) == pytest.approx(0.0)


def test_discount_depth_fake_mrp_cap_triggers():
    from src.db.models import MerchantProduct
    from src.services.intelligence.deal_scoring import FAKE_MRP_SCORE_CAP, discount_depth

    # 80% claimed discount would otherwise score 1.0, but the correlated
    # MerchantProduct shows the real current price is >5% above the deal's
    # claimed price -- fake-MRP protection caps it at FAKE_MRP_SCORE_CAP.
    deal = _deal(discount_percent=80.0, current_price=1000.0)
    overpriced = MerchantProduct(merchant_id=1, external_id="x", current_price=1200.0)
    assert discount_depth(deal, overpriced) == pytest.approx(FAKE_MRP_SCORE_CAP)


def test_discount_depth_within_tolerance_not_capped():
    from src.db.models import MerchantProduct
    from src.services.intelligence.deal_scoring import discount_depth

    deal = _deal(discount_percent=30.0, current_price=1000.0)
    product = MerchantProduct(merchant_id=1, external_id="x", current_price=1040.0)  # +4%, within 5% tolerance
    assert discount_depth(deal, product) == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# freshness -- pure, no DB
# --------------------------------------------------------------------------- #
def test_freshness_decays_with_age():
    from src.services.intelligence.deal_scoring import freshness

    now = datetime.now(timezone.utc)
    fresh_deal = _deal()
    fresh_deal.created_at = now
    day_old_deal = _deal()
    day_old_deal.created_at = now - timedelta(hours=24)

    assert freshness(fresh_deal, now=now) == pytest.approx(1.0, abs=1e-6)
    assert freshness(day_old_deal, now=now) == pytest.approx(math.exp(-1), rel=1e-3)


def test_freshness_unknown_when_no_created_at():
    from src.services.intelligence.deal_scoring import freshness

    deal = _deal()
    deal.created_at = None
    assert freshness(deal) == 0.5


# --------------------------------------------------------------------------- #
# price_credibility -- pure, no DB
# --------------------------------------------------------------------------- #
def test_price_credibility_bands():
    from src.db.models import MerchantProduct
    from src.services.intelligence.deal_scoring import price_credibility

    now = datetime.now(timezone.utc)
    fresh = MerchantProduct(merchant_id=1, external_id="a", availability="in_stock",
                            last_verified_at=now - timedelta(hours=1))
    stale = MerchantProduct(merchant_id=1, external_id="b", availability="in_stock",
                            last_verified_at=now - timedelta(hours=5))
    old = MerchantProduct(merchant_id=1, external_id="c", availability="in_stock",
                          last_verified_at=now - timedelta(hours=20))
    out_of_stock = MerchantProduct(merchant_id=1, external_id="d", availability="out_of_stock",
                                   last_verified_at=now - timedelta(minutes=5))

    assert price_credibility(_deal(), fresh, now=now) == 1.0
    assert price_credibility(_deal(), stale, now=now) == 0.7
    assert price_credibility(_deal(), old, now=now) == 0.3
    assert price_credibility(_deal(), out_of_stock, now=now) == 0.0
    assert price_credibility(_deal(), None, now=now) == 0.3


# --------------------------------------------------------------------------- #
# time_fit -- pure, no DB
# --------------------------------------------------------------------------- #
def test_time_fit_within_window_is_full_score():
    from src.services.intelligence.deal_scoring import time_fit

    assert time_fit("21-23", now_ist_hour=18) == 1.0   # bucket starts in 3h, within the 6h window
    assert time_fit(None, now_ist_hour=10) == 0.5       # no reliable best bucket -> neutral


def test_time_fit_linear_falloff_beyond_window():
    from src.services.intelligence.deal_scoring import time_fit

    # best bucket "09-11" starts 15h from now (18:00) -> falloff = 1 - (15-6)/18
    v = time_fit("09-11", now_ist_hour=18)
    assert v == pytest.approx(1 - (15 - 6) / 18, abs=1e-4)
    assert 0.0 <= v <= 1.0


# --------------------------------------------------------------------------- #
# scarcity_of_coverage -- pure, no DB
# --------------------------------------------------------------------------- #
def test_scarcity_of_coverage_scales_and_caps():
    from src.services.intelligence.deal_scoring import scarcity_of_coverage

    assert scarcity_of_coverage(None, {}) == 0.5             # unknown merchant -> neutral
    assert scarcity_of_coverage("boat", {}) == 1.0            # no competitor coverage -> fully scarce
    assert scarcity_of_coverage("boat", {"boat": 5}) == 0.0
    assert scarcity_of_coverage("boat", {"boat": 10}) == 0.0  # never goes negative
    assert scarcity_of_coverage("boat", {"boat": 2}) == pytest.approx(1 - 2 / 5)


# --------------------------------------------------------------------------- #
# Out-of-range guards -- every component stays within [0, 1] for extreme inputs
# --------------------------------------------------------------------------- #
def test_all_components_stay_in_unit_range_for_extreme_inputs():
    from src.services.intelligence.deal_scoring import (
        discount_depth, freshness, price_credibility, scarcity_of_coverage, time_fit,
    )

    extreme_deal = _deal(discount_percent=999.0)
    extreme_deal.created_at = datetime.now(timezone.utc) - timedelta(days=999)

    assert 0.0 <= discount_depth(extreme_deal, None) <= 1.0
    assert 0.0 <= freshness(extreme_deal) <= 1.0
    assert 0.0 <= price_credibility(extreme_deal, None) <= 1.0
    assert 0.0 <= time_fit("00-02", now_ist_hour=23) <= 1.0
    assert 0.0 <= scarcity_of_coverage("boat", {"boat": 999}) <= 1.0


# --------------------------------------------------------------------------- #
# DealScoringEngine.score_deal -- unknown merchant, no DB history needed
# --------------------------------------------------------------------------- #
def test_score_deal_unknown_merchant_defaults_to_neutral_components():
    from src.db.session import session_scope
    from src.services.intelligence.deal_scoring import DealScoringEngine

    deal = _deal(deal_id="ds_no_merchant", merchant_key=None, url=None, clean_url=None)
    with session_scope() as s:
        _, components = DealScoringEngine().score_deal(s, deal)
    assert components["audience_affinity"] == pytest.approx(0.5)
    assert components["scarcity_of_coverage"] == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# DealScoringEngine.score_all_active -- end to end, components sum to score
# --------------------------------------------------------------------------- #
def test_score_all_active_scores_valid_deals_and_components_sum_to_score():
    from sqlalchemy import select
    from src.db.models import Merchant, MerchantProduct
    from src.db.models_deal_score import DealScore
    from src.db.models_generation import DealValidity, EnrichedDeal
    from src.db.session import session_scope
    from src.services.intelligence.deal_scoring import WEIGHTS, DealScoringEngine

    with session_scope() as s:
        m = Merchant(key="boat_ds_test", display_name="boat")
        s.add(m)
        s.flush()
        s.add(MerchantProduct(
            merchant_id=m.id, external_id="p1", product_url="https://boat.example/ds1",
            current_price=999.0, availability="in_stock", last_verified_at=datetime.now(timezone.utc),
        ))
        valid = EnrichedDeal(
            deal_id="ds_valid_1", merchant_key="unknown_merchant_xyz", discount_percent=40.0,
            current_price=999.0, original_price=1500.0,
            url="https://boat.example/ds1", clean_url="https://boat.example/ds1",
            deal_validity=DealValidity.VALID,
        )
        invalid = EnrichedDeal(
            deal_id="ds_invalid_1", merchant_key="unknown_merchant_xyz", discount_percent=40.0,
            current_price=999.0, original_price=1500.0, deal_validity=DealValidity.INVALID,
        )
        s.add_all([valid, invalid])
        s.flush()
        valid_id, invalid_id = valid.id, invalid.id

    with session_scope() as s:
        n = DealScoringEngine().score_all_active(s)
    assert n >= 1

    with session_scope() as s:
        rows = s.scalars(select(DealScore)).all()
        scored_deal_ids = {r.deal_id for r in rows}
        assert valid_id in scored_deal_ids
        assert invalid_id not in scored_deal_ids   # invalid deals are never scored

        row = next(r for r in rows if r.deal_id == valid_id)
        expected_score = round(100.0 * sum(WEIGHTS[k] * row.components[k] for k in WEIGHTS), 3)
        assert row.score == pytest.approx(expected_score)
        # merchant has no owned-post engagement history -> audience_affinity defaults to 0.5
        assert row.components["audience_affinity"] == pytest.approx(0.5)
        for k, v in row.components.items():
            assert 0.0 <= v <= 1.0, f"component {k}={v} out of [0,1]"
        assert 0.0 <= row.score <= 100.0
