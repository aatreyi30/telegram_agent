# be/tests/test_merchants_mix.py
from __future__ import annotations
import os, tempfile
from datetime import datetime, timezone
import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db, session_scope
    from src.db.models import Competitor
    from src.db.models_intelligence import MerchantProfile, MERCHANT_INTEL_VERSION
    from src.db.models_competitor_intel import CompetitorProfile, COMPETITOR_INTEL_VERSION
    from src.db.models_normalization import NormalizedPost, SourceType

    init_db()
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        s.add(MerchantProfile(
            intel_version=MERCHANT_INTEL_VERSION, merchant_key="amazon",
            post_count_owned=60, avg_views_per_day=100.0, price_median=999.0,
            price_sample_size=12, confidence=0.8, computed_at=now))
        s.add(MerchantProfile(
            intel_version=MERCHANT_INTEL_VERSION, merchant_key="flipkart",
            post_count_owned=40, avg_views_per_day=80.0, price_median=499.0,
            price_sample_size=8, confidence=0.7, computed_at=now))

        comp = Competitor(username="rival_deals", access_status="public")
        s.add(comp)
        s.flush()
        s.add(CompetitorProfile(
            intel_version=COMPETITOR_INTEL_VERSION, competitor_id=comp.id,
            username="rival_deals", post_count=100,
            merchant_mix={"amazon": 69, "myntra": 31}, merchant_coverage=0.9,
            confidence=0.6, computed_at=now))

        # 10 owned normalized posts, 7 resolved to a merchant (5 amazon + 2 flipkart), 3 not
        for i in range(10):
            s.add(NormalizedPost(
                source_type=SourceType.OWNED, source_id=i + 1, normalized_at=now,
                primary_merchant_key=("amazon" if i < 5 else "flipkart" if i < 7 else None)))
    yield


def test_merchants_mix_contract():
    # The /api/merchants HTTP route (and its service.merchants() facade) was
    # removed as a UI-only cut, but the underlying merchant intelligence
    # engine + grounding context (src.ai.context) stay fully intact — this
    # test now exercises those directly.
    from src.ai import context as ctx
    from src.db.session import session_scope

    with session_scope() as s:
        profiles = ctx.merchant_profiles(s)
        assert len(profiles) == 2
        assert "price_sample_size" in profiles[0]

        coverage = ctx.owned_merchant_coverage(s)
        assert coverage["total"] == 10
        assert coverage["resolved"] == 7
        assert coverage["pct"] == pytest.approx(0.7)

        mix = ctx.merchant_mix(s, owned_coverage_pct=coverage["pct"])

    channels = {c["name"]: c for c in mix["channels"]}
    assert "You" in channels
    you = channels["You"]
    assert you["is_owned"] is True
    assert sum(you["shares"].values()) == pytest.approx(1.0)

    assert "rival_deals" in channels
    rival = channels["rival_deals"]
    assert rival["is_owned"] is False
    assert rival["shares"]["amazon"] == pytest.approx(69 / 100)
    assert rival["shares"]["myntra"] == pytest.approx(31 / 100)
    assert sum(rival["shares"].values()) == pytest.approx(1.0)

    assert set(mix["merchants"]) == {"amazon", "flipkart", "myntra"}
