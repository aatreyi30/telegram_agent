"""Deal-dimension intelligence (Track A) — AC1-AC5.

AC1: parser.parse_discount_pct/discount_band/price_band/infer_category over
     the real post-text shapes from the spec.
AC2: PostNormalizer._normalize_one populates category/discount_pct/
     discount_band/price_band on NormalizedPost, for both owned + competitor.
AC3: analytics.views.compute() exposes by_category/by_discount_band/
     by_price_band + a gated `segments` leaderboard.
AC4: analytics.deal_gap.compute() — per-category owned vs competitor share.
AC5: ai.planner.build_plan_context gains `segment_performance`, and its
     numbers land in generate_day_plan's factcheck `facts` pool.
"""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timedelta, timezone

import pytest

from src.services.processing import parser

# --------------------------------------------------------------------------- #
# AC1 — pure parser functions, over the real sample texts from the spec
# --------------------------------------------------------------------------- #

PUMA_TEXT = ("\U0001F45F Run in PUMA. Pay Less.\n\nPUMA Essex Comfort Running Shoes\n\n"
             "Today's Price: ₹877\n\n\U0001F449 Lace Up: https://grbn.in/zrsfS9")
BOAT_TEXT = "boAt Airdopes 212\n\n50 Hours Playback\n\nNow at ₹799   (76% OFF)"
BOTTLE_TEXT = "\U0001F4A7EXODUS 2L Motivational Water Bottle\n\nDeal Price ₹80\nYou Save 84%"
TOWEL_TEXT = ("\U0001F6C1 Towel Essentials Loot \U0001F525\U0001F60D\n\U0001F4A5 Under ₹500 "
              "\U0001F6D2\U0001F525\n\nBath Towels & Robes - x\nTowel Sets - y")
TOPS_TEXT = ("Women's Top Loot under ₹500 ✨\U0001F60D\n\nCrop Tops - x\nPrinted Tops - y")


def test_parse_discount_pct_handles_all_three_shapes():
    assert parser.parse_discount_pct(BOAT_TEXT) == 76.0
    assert parser.parse_discount_pct(BOTTLE_TEXT) == 84.0
    assert parser.parse_discount_pct("Flat 50% off on everything") == 50.0


def test_parse_discount_pct_absent_and_implausible():
    assert parser.parse_discount_pct(PUMA_TEXT) is None
    assert parser.parse_discount_pct("Rated 100% 5 stars") is None  # >=100 rejected
    assert parser.parse_discount_pct(None) is None


def test_discount_band_fixed_thresholds():
    assert parser.discount_band(76.0) == "70%+"
    assert parser.discount_band(69.9) == "50-69%"
    assert parser.discount_band(50.0) == "50-69%"
    assert parser.discount_band(30.0) == "30-49%"
    assert parser.discount_band(10.0) == "<30%"
    assert parser.discount_band(None) is None


def test_price_band_from_stated_price():
    prices = parser.parse_prices(BOAT_TEXT)  # 799
    assert parser.price_band(prices, None) == "500-999"
    prices = parser.parse_prices(BOTTLE_TEXT)  # 80
    assert parser.price_band(prices, None) == "under-299"


def test_price_band_from_threshold_when_no_price_stated():
    threshold = parser.parse_price_threshold(TOWEL_TEXT)  # "Under ₹500"
    assert threshold == 500.0
    # A ceiling bands by what it EXCLUDES: "Under ₹500" advertises items below 500, so it
    # belongs with the budget band, not filed next to premium 500-999 deals.
    assert parser.price_band([], threshold) == "300-499"


def test_price_band_none_when_neither_present():
    assert parser.price_band([], None) is None


def test_price_band_none_for_multi_deal_loot_board():
    # A loot board listing ₹80 and ₹2999 has no single "the deal price" —
    # banding on the cheapest item would skew the leaderboard to under-299.
    prices = parser.parse_prices("Item A ₹80, Item B ₹2999")
    assert parser.price_band(prices, None, is_multi_deal=True) is None
    # same prices, single deal -> still bands normally
    assert parser.price_band(prices, None, is_multi_deal=False) == "under-299"


def test_parse_discount_pct_takes_highest_cue_not_first():
    # "Flat 10% extra off ... 76% OFF" — the first cue match (10) is not the
    # headline discount; the highest plausible value must win.
    assert parser.parse_discount_pct("Flat 10% extra off on top of 76% OFF everything") == 76.0


def test_infer_category_from_text():
    assert parser.infer_category(PUMA_TEXT, None) == "fashion-and-lifestyle"
    assert parser.infer_category(BOAT_TEXT, None) == "electronics-and-gadgets"
    assert parser.infer_category(BOTTLE_TEXT, None) == "home-and-living"
    assert parser.infer_category(TOWEL_TEXT, None) == "home-and-living"
    assert parser.infer_category(TOPS_TEXT, None) == "fashion-and-lifestyle"


def test_infer_category_never_guesses_from_merchant_alone():
    # AC1 forbids inferring category from the merchant with zero textual
    # evidence — even for a merchant whose catalogue is reliably one category.
    assert parser.infer_category("Grab this deal now, link below.", "boat") is None
    assert parser.infer_category("Grab this deal now, link below.", "myntra") is None
    assert parser.infer_category("Grab this deal now, link below.", "nykaa") is None
    # text keywords still win when present, merchant is irrelevant either way
    assert parser.infer_category(PUMA_TEXT, "boat") == "fashion-and-lifestyle"


def test_infer_category_never_guesses_general():
    assert parser.infer_category("Grab this deal now, link below.", None) is None
    assert parser.infer_category(None, None) is None
    assert parser.infer_category("", "amazon") is None  # amazon has no category hint


# --------------------------------------------------------------------------- #
# AC2 — normalizer populates the new columns; DB-backed tests
# --------------------------------------------------------------------------- #


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_URL", f"sqlite:///{tmp_path}/dd.db")
    monkeypatch.setenv("RAW_SNAPSHOT_DIR", f"{tmp_path}/raw")
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db
    init_db()
    yield


def test_normalizer_populates_deal_dimensions_owned(isolated_db):
    from src.db.models import Channel, Post
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.db.session import session_scope
    from src.services.processing.normalizer import PostNormalizer

    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch); s.flush()
        p = Post(channel_id=ch.id, tg_message_id=1, text=BOAT_TEXT,
                  posted_at=datetime.now(timezone.utc), collected_at=datetime.now(timezone.utc),
                  content_sha256="h1")
        s.add(p); s.flush()

        n = PostNormalizer()
        n._normalize_one(s, SourceType.OWNED, p, [])

        from sqlalchemy import select
        np = s.scalar(select(NormalizedPost).where(NormalizedPost.source_type == SourceType.OWNED))
        assert np.category == "electronics-and-gadgets"
        assert np.discount_pct == 76.0
        assert np.discount_band == "70%+"
        assert np.price_band == "500-999"


def test_normalizer_populates_deal_dimensions_competitor(isolated_db):
    from src.db.models import Competitor, CompetitorPost
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.db.session import session_scope
    from src.services.processing.normalizer import PostNormalizer

    with session_scope() as s:
        comp = Competitor(username="riv", title="Riv")
        s.add(comp); s.flush()
        cp = CompetitorPost(competitor_id=comp.id, tg_message_id=1, text=TOWEL_TEXT,
                             posted_at=datetime.now(timezone.utc),
                             collected_at=datetime.now(timezone.utc), content_sha256="h2")
        s.add(cp); s.flush()

        n = PostNormalizer()
        n._normalize_one(s, SourceType.COMPETITOR, cp, [])

        from sqlalchemy import select
        np = s.scalar(select(NormalizedPost).where(NormalizedPost.source_type == SourceType.COMPETITOR))
        assert np.category == "home-and-living"
        assert np.price_band == "300-499"  # from the "Under ₹500" ceiling — a budget board


def test_renormalize_across_version_bump_preserves_link_resolution_state(isolated_db):
    """S1-c: re-normalizing a post (e.g. after a NORMALIZATION_VERSION bump)
    must not wipe ExtractedLink columns only the network resolver writes."""
    from sqlalchemy import select
    from src.db.models import Channel, Post
    from src.db.models_normalization import ExtractedLink, NormalizedPost, SourceType
    from src.db.session import session_scope
    from src.services.processing.normalizer import PostNormalizer

    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch); s.flush()
        p = Post(channel_id=ch.id, tg_message_id=1, text=PUMA_TEXT,
                  posted_at=datetime.now(timezone.utc), collected_at=datetime.now(timezone.utc),
                  content_sha256="h1")
        s.add(p); s.flush()
        post_id = p.id

        n = PostNormalizer()
        n._normalize_one(s, SourceType.OWNED, p, [])

    # simulate the network resolver (link_resolution.py) having resolved the
    # grbn.in shortlink on a prior run
    with session_scope() as s:
        link = s.scalar(select(ExtractedLink).where(ExtractedLink.url.like("%grbn.in%")))
        link.resolved_url = "https://www.puma.com/in/en/pd/shoes/123"
        link.merchant_key = "puma"
        link.resolution_status = "resolved"
        link.resolution_attempts = 1

    # re-normalize the SAME raw post (simulating a NORMALIZATION_VERSION bump
    # picking it up again) — must be idempotent w.r.t. resolver state
    with session_scope() as s:
        p = s.get(Post, post_id)
        n = PostNormalizer()
        n._normalize_one(s, SourceType.OWNED, p, [])

    with session_scope() as s:
        link = s.scalar(select(ExtractedLink).where(ExtractedLink.url.like("%grbn.in%")))
        assert link.resolved_url == "https://www.puma.com/in/en/pd/shoes/123"
        assert link.merchant_key == "puma"
        assert link.resolution_status == "resolved"
        assert link.resolution_attempts == 1

        np = s.scalar(select(NormalizedPost).where(NormalizedPost.source_type == SourceType.OWNED))
        # primary_merchant_key must also survive: raw-domain detection alone is
        # NULL for a grbn.in shortlink, so it must fall back to the resolved
        # merchant recorded on the link rather than regressing to None.
        assert np.primary_merchant_key == "puma"


# --------------------------------------------------------------------------- #
# AC3 — analytics.views.compute() segment leaderboards
# --------------------------------------------------------------------------- #


def test_views_compute_exposes_segments_gated_by_min_n(isolated_db):
    from src.db.models import Channel, Post
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.db.session import session_scope
    from src.services.analytics import views as vv

    base = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch); s.flush()
        # electronics: 5 posts, high engagement -> above the min-n gate
        for i in range(5):
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base - timedelta(hours=i),
                      collected_at=base, views=100, reactions_total=20, forwards=10)
            s.add(p); s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED, normalized_at=base,
                                 category="electronics-and-gadgets", discount_band="70%+"))
        # fashion: only 1 post -> below MIN_SEGMENT_N, must be excluded from segments
        p = Post(channel_id=ch.id, tg_message_id=99, posted_at=base, collected_at=base,
                  views=1000, reactions_total=500, forwards=500)
        s.add(p); s.flush()
        s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED, normalized_at=base,
                             category="fashion-and-lifestyle"))

    with session_scope() as s:
        a = vv.compute(s)

    assert {row["label"] for row in a["by_category"]} == {"electronics-and-gadgets", "fashion-and-lifestyle"}
    seg_labels = {(row["dimension"], row["label"]) for row in a["segments"]}
    assert ("category", "electronics-and-gadgets") in seg_labels
    assert ("category", "fashion-and-lifestyle") not in seg_labels  # gated out, n=1
    assert a["segments_min_n"] == vv.MIN_SEGMENT_N
    assert all(row["n"] >= vv.MIN_SEGMENT_N for row in a["segments"])


# --------------------------------------------------------------------------- #
# AC4 — competitor deal-gap
# --------------------------------------------------------------------------- #


def test_deal_gap_flags_competitor_over_indexed_category(isolated_db):
    from src.db.models import Channel, Competitor, CompetitorPost, Post
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.db.session import session_scope
    from src.services.analytics import deal_gap

    base = datetime.now(timezone.utc)
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch); s.flush()
        comp = Competitor(username="riv", title="Riv")
        s.add(comp); s.flush()

        # we post 0 beauty; competitor posts 6 beauty (over min sample) -> a gap
        for i in range(6):
            cp = CompetitorPost(competitor_id=comp.id, tg_message_id=i, posted_at=base,
                                 collected_at=base, content_sha256=f"c{i}")
            s.add(cp); s.flush()
            s.add(NormalizedPost(source_id=cp.id, source_type=SourceType.COMPETITOR,
                                 normalized_at=base, category="beauty-and-personal-care"))
        # both sides post electronics evenly -> no gap
        for i in range(6):
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base, collected_at=base)
            s.add(p); s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                 normalized_at=base, category="electronics-and-gadgets"))
            cp = CompetitorPost(competitor_id=comp.id, tg_message_id=100 + i, posted_at=base,
                                 collected_at=base, content_sha256=f"e{i}")
            s.add(cp); s.flush()
            s.add(NormalizedPost(source_id=cp.id, source_type=SourceType.COMPETITOR,
                                 normalized_at=base, category="electronics-and-gadgets"))

    with session_scope() as s:
        gap = deal_gap.compute(s, window_days=None)

    by_cat = {r["category"]: r for r in gap["rows"]}
    assert by_cat["beauty-and-personal-care"]["owned_n"] == 0
    assert by_cat["beauty-and-personal-care"]["over_indexed_by_competitors"] is True
    assert by_cat["electronics-and-gadgets"]["over_indexed_by_competitors"] is False
    assert gap["min_competitor_n"] == deal_gap.MIN_COMPETITOR_N


def test_deal_gap_omits_categories_below_min_competitor_sample(isolated_db):
    from src.db.models import Competitor, CompetitorPost
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.db.session import session_scope
    from src.services.analytics import deal_gap

    base = datetime.now(timezone.utc)
    with session_scope() as s:
        comp = Competitor(username="riv", title="Riv")
        s.add(comp); s.flush()
        cp = CompetitorPost(competitor_id=comp.id, tg_message_id=1, posted_at=base,
                             collected_at=base, content_sha256="only-one")
        s.add(cp); s.flush()
        s.add(NormalizedPost(source_id=cp.id, source_type=SourceType.COMPETITOR,
                             normalized_at=base, category="health-and-wellness"))

    with session_scope() as s:
        gap = deal_gap.compute(s, window_days=None)

    assert gap["rows"] == []  # 1 < MIN_COMPETITOR_N, never reported


# --------------------------------------------------------------------------- #
# AC5 — build_plan_context / generate_day_plan factcheck pool
# --------------------------------------------------------------------------- #


def test_build_plan_context_includes_segment_performance(isolated_db):
    from src.db.models import Channel, Post
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.db.session import session_scope
    from src.ai.planner import build_plan_context

    base = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch); s.flush()
        for i in range(5):
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base - timedelta(days=i),
                      collected_at=base, views=100, reactions_total=20, forwards=10)
            s.add(p); s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED, normalized_at=base,
                                 category="electronics-and-gadgets"))

    with session_scope() as s:
        ctx = build_plan_context(s, date(2026, 7, 8))

    seg = ctx["segment_performance"]
    assert seg["available"] is True
    assert any(row["label"] == "electronics-and-gadgets" for row in seg["top_categories"])
    assert seg["min_n"] > 0


def test_generate_day_plan_facts_pool_verifies_segment_numbers(monkeypatch, isolated_db):
    from src.db.models import Channel, Post
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.db.session import session_scope
    from src.ai import planner
    from src.ai.factcheck import check_cited_numbers

    base = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch); s.flush()
        for i in range(5):
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base - timedelta(hours=i),
                      collected_at=base, views=100, reactions_total=20, forwards=10)
            s.add(p); s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED, normalized_at=base,
                                 category="electronics-and-gadgets"))

    with session_scope() as s:
        pctx = planner.build_plan_context(s, date(2026, 7, 1))
    seg_row = pctx["segment_performance"]["top_categories"][0]
    engagement_rate = seg_row["engagement_rate"]

    canned = (
        f"Digest.\n===PLAN===\n"
        '{"date":"2026-07-01","recommended_posts":1,'
        # per-post shape (`time_ist`, no count) — the schema the planner actually emits.
        # This test previously used the legacy `window_ist` form, so AC5's factcheck path
        # was never exercised against the shape that ships.
        '"post_slots":[{"type":"single","time_ist":"18:20","theme":"electronics-and-gadgets",'
        f'"merchant":"amazon","why":"posting at 18:20 — electronics-and-gadgets engagement rate {engagement_rate}"}}],'
        f'"emphasis":"x","watch":"y","cited_numbers":[{engagement_rate}]}}'
    )
    monkeypatch.setattr(planner.AIClient, "complete", lambda self, *a, **k: canned)

    with session_scope() as s:
        res = planner.generate_day_plan(s, day=date(2026, 7, 1))

    assert res["available"]
    fc = check_cited_numbers(res["plan"]["cited_numbers"], res["facts"])
    assert fc["status"] == "passed", fc["unverified"]
