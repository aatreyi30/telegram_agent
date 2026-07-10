# be/tests/test_competitor_trends.py
"""Coverage for the per-competitor daily trend charts (competitor_trends.py).

Mirrors the isolated-DB fixture style of test_ist_day_boundary.py, including a
post planted right at the IST/UTC day boundary, to confirm every bucketing here
goes through periods.py's canonical helpers instead of reintroducing the naive
UTC-day bug that test_ist_day_boundary.py documents.
"""
from __future__ import annotations

import os
import statistics
import tempfile
from datetime import datetime, timezone

import pytest

COMP1_ID = None
COMP2_ID = None
COMP3_ID = None


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    global COMP1_ID, COMP2_ID, COMP3_ID
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db, session_scope
    from src.db.models import Competitor, CompetitorPost
    from src.db.models_normalization import NormalizedPost, SourceType

    init_db()

    def _post(competitor_id, tg_message_id, posted_at, text, has_media, views,
              forwards, reactions_total, links):
        return CompetitorPost(
            competitor_id=competitor_id, tg_message_id=tg_message_id, posted_at=posted_at,
            text=text, has_media=has_media, views=views, forwards=forwards,
            reactions_total=reactions_total, links=links, collected_at=posted_at,
        )

    def _norm(source_id, num_links, primary_merchant_key, is_multi_deal, normalized_at):
        return NormalizedPost(
            source_id=source_id, source_type=SourceType.COMPETITOR, normalized_at=normalized_at,
            num_links=num_links, primary_merchant_key=primary_merchant_key,
            is_multi_deal=is_multi_deal,
        )

    with session_scope() as s:
        c1 = Competitor(username="rivalco", category="channel")
        s.add(c1); s.flush()
        COMP1_ID = c1.id

        p1_at = datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc)  # 15:30 IST Jul 6
        p1 = _post(c1.id, 101, p1_at, "Flat 50% off Amazon deal", True, 100, 5, 10,
                   ["https://amazon.in/deal1"])
        s.add(p1); s.flush()
        s.add(_norm(p1.id, 1, "amazon", False, p1_at))

        p2_at = datetime(2026, 7, 7, 10, 0, 0, tzinfo=timezone.utc)  # 15:30 IST Jul 7
        p2 = _post(c1.id, 102, p2_at, "Loot deal bonanza flipkart", False, 200, 2, None,
                   ["https://flipkart.com/deal2"])
        s.add(p2); s.flush()
        s.add(_norm(p2.id, 1, "flipkart", True, p2_at))

        # Deliberately un-normalized post on the same IST day as p2 — must still be
        # counted by the CompetitorPost-only trends (posting/views/media) but
        # excluded from the NormalizedPost-joined trends (merchant/content-mix/links).
        p5_at = datetime(2026, 7, 7, 11, 0, 0, tzinfo=timezone.utc)
        p5 = _post(c1.id, 105, p5_at, "second post no norm", True, 10, 1, 2, None)
        s.add(p5)

        p3_at = datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc)  # 15:30 IST Jul 8
        p3 = _post(c1.id, 103, p3_at, "short", True, 50, 0, 1, None)
        s.add(p3); s.flush()
        s.add(_norm(p3.id, 0, None, False, p3_at))

        # 2026-07-08 18:34:39 UTC == 2026-07-09 00:04:39 IST — the same boundary
        # case as test_ist_day_boundary.py: true IST day is July 9, not July 8.
        p4_at = datetime(2026, 7, 8, 18, 34, 39, tzinfo=timezone.utc)
        p4 = _post(c1.id, 104, p4_at, "Big Amazon sale bonanza", False, 300, 8, 20,
                   ["https://amazon.in/deal4"])
        s.add(p4); s.flush()
        s.add(_norm(p4.id, 1, "amazon", True, p4_at))

        # Second competitor, dedicated to caption_length_distribution — dates don't
        # matter there, only text length, so keep it isolated from the day-window
        # assertions above.
        c2 = Competitor(username="lengthtest", category="channel")
        s.add(c2); s.flush()
        COMP2_ID = c2.id
        lt_at = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        for i, text in enumerate(["A" * 30, None, "B" * 70, "C" * 150, "D" * 300, "E" * 450]):
            s.add(_post(c2.id, 200 + i, lt_at, text, False, 1, 0, 0, None))

        # Third competitor with zero posts, for the "no data yet" edge case.
        c3 = Competitor(username="emptyco", category="channel")
        s.add(c3); s.flush()
        COMP3_ID = c3.id
    yield


def test_posting_trend_buckets_across_ist_boundary():
    from src.db.session import session_scope
    from src.services.analytics import competitor_trends as ct

    with session_scope() as s:
        result = ct.posting_trend(s, COMP1_ID, days=4)
    by_date = {d["date"]: d["posts"] for d in result["days"]}
    assert by_date == {
        "2026-07-06": 1, "2026-07-07": 2, "2026-07-08": 1, "2026-07-09": 1,
    }


def test_views_trend():
    from src.db.session import session_scope
    from src.services.analytics import competitor_trends as ct

    with session_scope() as s:
        result = ct.views_trend(s, COMP1_ID, days=4)
    by_date = {d["date"]: (d["total_views"], d["avg_views"]) for d in result["days"]}
    assert by_date == {
        "2026-07-06": (100, 100.0),
        "2026-07-07": (210, 105.0),
        "2026-07-08": (50, 50.0),
        "2026-07-09": (300, 300.0),
    }


def test_merchant_trend_excludes_unnormalized_posts():
    from src.db.session import session_scope
    from src.services.analytics import competitor_trends as ct

    with session_scope() as s:
        result = ct.merchant_trend(s, COMP1_ID, days=4)
    assert set(result["merchants"]) == {"amazon", "flipkart", "unknown"}
    by_date = {d["date"]: d["counts"] for d in result["days"]}
    assert by_date["2026-07-06"]["amazon"] == 1
    assert by_date["2026-07-07"]["flipkart"] == 1
    assert by_date["2026-07-07"]["amazon"] == 0  # p5 (unnormalized) not double-counted
    assert by_date["2026-07-08"]["unknown"] == 1  # p3 has no merchant_key
    assert by_date["2026-07-09"]["amazon"] == 1


def test_content_mix_trend():
    from src.db.session import session_scope
    from src.services.analytics import competitor_trends as ct

    with session_scope() as s:
        result = ct.content_mix_trend(s, COMP1_ID, days=4)
    by_date = {d["date"]: (d["single_deal"], d["loot_deal"]) for d in result["days"]}
    assert by_date == {
        "2026-07-06": (1, 0), "2026-07-07": (0, 1), "2026-07-08": (1, 0), "2026-07-09": (0, 1),
    }


def test_media_text_trend_includes_unnormalized_post():
    from src.db.session import session_scope
    from src.services.analytics import competitor_trends as ct

    with session_scope() as s:
        result = ct.media_text_trend(s, COMP1_ID, days=4)
    by_date = {d["date"]: (d["media"], d["text"]) for d in result["days"]}
    assert by_date["2026-07-07"] == (1, 1)  # p2 (text) + p5 (media), unlike content_mix_trend


def test_link_usage_trend():
    from src.db.session import session_scope
    from src.services.analytics import competitor_trends as ct

    with session_scope() as s:
        result = ct.link_usage_trend(s, COMP1_ID, days=4)
    by_date = {d["date"]: d["avg_links"] for d in result["days"]}
    assert by_date == {
        "2026-07-06": 1.0, "2026-07-07": 1.0, "2026-07-08": 0.0, "2026-07-09": 1.0,
    }


def test_top_posts_ranked_by_views():
    from src.db.session import session_scope
    from src.services.analytics import competitor_trends as ct

    with session_scope() as s:
        result = ct.top_posts(s, COMP1_ID, limit=10)
    assert [p["views"] for p in result] == [300, 200, 100, 50, 10]
    top = result[0]
    assert top["forwards"] == 8
    assert top["reactions_total"] == 20
    assert top["link"] == "https://amazon.in/deal4"
    assert top["text_snippet"] == "Big Amazon sale bonanza"
    no_link_post = next(p for p in result if p["views"] == 50)
    assert no_link_post["link"] is None


def test_caption_length_distribution_buckets():
    from src.db.session import session_scope
    from src.services.analytics import competitor_trends as ct

    with session_scope() as s:
        result = ct.caption_length_distribution(s, COMP2_ID)
    by_range = {b["range"]: b["count"] for b in result["buckets"]}
    assert by_range == {"0-50": 2, "50-100": 1, "100-200": 1, "200-400": 1, "400+": 1}


def test_posting_consistency_reuses_posting_trend():
    from src.db.session import session_scope
    from src.services.analytics import competitor_trends as ct

    with session_scope() as s:
        result = ct.posting_consistency(s, COMP1_ID, days=4)
    expected = [1, 2, 1, 1]
    assert result["daily_counts"] == expected
    assert result["mean"] == pytest.approx(statistics.fmean(expected), abs=0.01)
    assert result["stdev"] == pytest.approx(statistics.pstdev(expected), abs=0.01)
    assert result["variance"] == pytest.approx(statistics.pvariance(expected), abs=0.01)


def test_empty_competitor_returns_empty_series_not_errors():
    from src.db.session import session_scope
    from src.services.analytics import competitor_trends as ct

    with session_scope() as s:
        assert ct.posting_trend(s, COMP3_ID, days=30) == {"days": []}
        assert ct.merchant_trend(s, COMP3_ID, days=30) == {"merchants": [], "days": []}
        assert ct.top_posts(s, COMP3_ID) == []
        consistency = ct.posting_consistency(s, COMP3_ID, days=30)
        assert consistency == {"daily_counts": [], "mean": 0.0, "stdev": 0.0, "variance": 0.0}


def test_all_trends_aggregates_every_metric():
    from src.db.session import session_scope
    from src.services.analytics import competitor_trends as ct

    with session_scope() as s:
        result = ct.all_trends(s, COMP1_ID, days=4)
    assert set(result.keys()) == {
        "posting_trend", "views_trend", "merchant_trend", "top_posts",
        "content_mix_trend", "media_text_trend", "link_usage_trend",
        "caption_length_distribution", "posting_consistency",
    }
    assert len(result["top_posts"]) == 5


def test_service_competitor_trends_not_found():
    from src.controllers import service

    result = service.competitor_trends(999999, days=30)
    assert result == {"ok": False, "error": "Competitor not found"}


def test_service_competitor_trends_known_id():
    from src.controllers import service

    result = service.competitor_trends(COMP1_ID, days=4)
    assert "posting_trend" in result
    assert result["posting_trend"]["days"][0]["date"] == "2026-07-06"
