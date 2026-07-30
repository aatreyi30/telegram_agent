"""Punchlist-1 GROUP D — segment/deal-gap honesty fixes.

S2-f: segment_performance carries its window and top/bottom categories are
      disjoint (no row is simultaneously "top" and "bottom").
S2-d: views.compute() reports a categorized/total coverage pair per
      dimension, and the ungated by_category/by_discount_band/by_price_band
      rows are marked when they're below the segment min-n gate.
S2-e: deal_gap.compute() reports each side's categorized/total coverage so
      "share of posts" can be checked against differently-covered
      populations instead of trusted at face value.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_URL", f"sqlite:///{tmp_path}/sh.db")
    monkeypatch.setenv("RAW_SNAPSHOT_DIR", f"{tmp_path}/raw")
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db
    init_db()
    yield


# --------------------------------------------------------------------------- #
# S2-f — segment_performance window label + disjoint top/bottom
# --------------------------------------------------------------------------- #


def test_segment_performance_carries_window(isolated_db):
    from src.db.models import Channel, Post
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.db.session import session_scope
    from src.services.analytics import views as vv

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
        seg = vv.segment_performance(s)

    # Every other fact fed to the daily plan is labelled with its window;
    # this one must be too — an unlabelled dict is what shipped before.
    assert "window" in seg
    assert seg["window"]["n"] == 5
    assert seg["window"]["start"] is not None
    assert seg["window"]["end"] is not None


def test_segment_performance_top_bottom_disjoint(isolated_db):
    """4 categories, top_n=3: the old `cats[-top_n:]` bottom slice overlapped
    the top slice (cats[0:3] vs cats[1:4]) — rows 1 and 2 were labelled BOTH
    top and bottom in the same prompt payload."""
    from src.db.models import Channel, Post
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.db.session import session_scope
    from src.services.analytics import views as vv

    base = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    categories = ["electronics-and-gadgets", "fashion-and-lifestyle",
                  "beauty-and-personal-care", "home-and-living"]
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch); s.flush()
        mid = 0
        # descending engagement rate per category so ranking is deterministic:
        # give each category a distinct reaction count, same views/n across all.
        for ci, cat in enumerate(categories):
            reactions = 100 - ci * 10  # strictly decreasing engagement rate
            for i in range(3):  # >= MIN_SEGMENT_N so all 4 make the leaderboard
                mid += 1
                p = Post(channel_id=ch.id, tg_message_id=mid, posted_at=base - timedelta(hours=mid),
                          collected_at=base, views=100, reactions_total=reactions, forwards=0)
                s.add(p); s.flush()
                s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                     normalized_at=base, category=cat))

    with session_scope() as s:
        seg = vv.segment_performance(s, top_n=3)

    top_labels = {row["label"] for row in seg["top_categories"]}
    bottom_labels = {row["label"] for row in seg["bottom_categories"]}
    assert not (top_labels & bottom_labels), (
        f"top/bottom overlap: {top_labels & bottom_labels}"
    )
    assert len(top_labels) == 3
    assert bottom_labels == {"home-and-living"}  # the single remaining, lowest-engagement row


# --------------------------------------------------------------------------- #
# S2-d — dimension coverage denominators + below-min-n marking
# --------------------------------------------------------------------------- #


def test_compute_reports_dimension_coverage(isolated_db):
    from src.db.models import Channel, Post
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.db.session import session_scope
    from src.services.analytics import views as vv

    base = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch); s.flush()
        # 2 categorized posts
        for i in range(2):
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base - timedelta(hours=i),
                      collected_at=base, views=100, reactions_total=10, forwards=0)
            s.add(p); s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED, normalized_at=base,
                                 category="electronics-and-gadgets"))
        # 3 uncategorized posts (category=None) -> must count in `total` but not `categorized`
        for i in range(3):
            p = Post(channel_id=ch.id, tg_message_id=10 + i, posted_at=base - timedelta(hours=10 + i),
                      collected_at=base, views=50, reactions_total=5, forwards=0)
            s.add(p); s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED, normalized_at=base,
                                 category=None))

    with session_scope() as s:
        a = vv.compute(s)

    cov = a["dimension_coverage"]["category"]
    assert cov == {"categorized": 2, "total": 5}
    # nothing categorized as discount_band/price_band in this fixture -> all 5 uncategorized
    assert a["dimension_coverage"]["discount_band"] == {"categorized": 0, "total": 5}
    assert a["dimension_coverage"]["price_band"] == {"categorized": 0, "total": 5}


def test_by_category_marks_rows_below_segment_min_n(isolated_db):
    from src.db.models import Channel, Post
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.db.session import session_scope
    from src.services.analytics import views as vv

    base = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch); s.flush()
        # electronics: 5 posts -> meets MIN_SEGMENT_N
        for i in range(5):
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base - timedelta(hours=i),
                      collected_at=base, views=100, reactions_total=20, forwards=10)
            s.add(p); s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED, normalized_at=base,
                                 category="electronics-and-gadgets"))
        # fashion: 1 post, 100% engagement -> below MIN_SEGMENT_N but still in by_category
        p = Post(channel_id=ch.id, tg_message_id=99, posted_at=base, collected_at=base,
                  views=10, reactions_total=10, forwards=0)
        s.add(p); s.flush()
        s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED, normalized_at=base,
                             category="fashion-and-lifestyle"))

    with session_scope() as s:
        a = vv.compute(s)

    by_label = {row["label"]: row for row in a["by_category"]}
    assert by_label["electronics-and-gadgets"]["below_min_n"] is False
    assert by_label["fashion-and-lifestyle"]["below_min_n"] is True


# --------------------------------------------------------------------------- #
# S2-e — deal_gap coverage denominators
# --------------------------------------------------------------------------- #


def test_deal_gap_reports_coverage_for_each_side(isolated_db):
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

        # owned: 2 categorized, 3 uncategorized (category=None) -> coverage 2/5
        for i in range(2):
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base, collected_at=base)
            s.add(p); s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                 normalized_at=base, category="electronics-and-gadgets"))
        for i in range(3):
            p = Post(channel_id=ch.id, tg_message_id=10 + i, posted_at=base, collected_at=base)
            s.add(p); s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                 normalized_at=base, category=None))

        # competitor: 6 categorized (over MIN_COMPETITOR_N), 0 uncategorized -> coverage 6/6
        for i in range(6):
            cp = CompetitorPost(competitor_id=comp.id, tg_message_id=i, posted_at=base,
                                 collected_at=base, content_sha256=f"c{i}")
            s.add(cp); s.flush()
            s.add(NormalizedPost(source_id=cp.id, source_type=SourceType.COMPETITOR,
                                 normalized_at=base, category="beauty-and-personal-care"))

    with session_scope() as s:
        gap = deal_gap.compute(s, window_days=None)

    assert gap["owned_coverage"] == {"categorized": 2, "total": 5}
    assert gap["competitor_coverage"] == {"categorized": 6, "total": 6}
