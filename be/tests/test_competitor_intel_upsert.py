"""Competitor intel upsert + monitoring gate (revert of the Phase 0.1 versioned-
snapshot design -- see CompetitorProfile's docstring). Covers:

  * Running `CompetitorIntelligenceEngine.run()` twice never duplicates a
    competitor's profile row (the whole point of restoring
    UNIQUE(intel_version, competitor_id) and upserting instead of inserting)
    and the second run refreshes the row's fields in place.
  * Benchmarks are replaced (delete+insert), not accumulated.
  * A competitor with `monitoring_enabled=False` is skipped by the engine
    entirely -- no profile/benchmark row is written for it.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

UTC = timezone.utc


@pytest.fixture(scope="function", autouse=True)
def _isolated_db():
    # function-scoped (not module-scoped like most other test files here): each
    # test seeds its own competitor set and asserts on `result.processed`/exact
    # row counts, which would be polluted by competitors left over from an
    # earlier test in the same module if the DB were shared.
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    os.environ["SCHEDULERS_AUTOSTART"] = "false"
    from src.config.settings import get_settings
    from src.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db

    init_db()
    yield


def _seed_competitor(username: str, n_posts: int, monitoring_enabled: bool = True) -> int:
    """A competitor with `n_posts` normalized competitor posts (own helper --
    real collection/normalization is out of scope here). Returns the
    competitor id."""
    from src.db.models import Competitor, CompetitorPost
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.db.session import session_scope

    now = datetime.now(UTC)
    with session_scope() as s:
        comp = Competitor(username=username, monitoring_enabled=monitoring_enabled)
        s.add(comp)
        s.flush()
        cid = comp.id
        for i in range(n_posts):
            cp = CompetitorPost(
                competitor_id=cid, tg_message_id=1000 + i,
                posted_at=now - timedelta(days=i), text=f"deal number {i}",
                collected_at=now,
            )
            s.add(cp)
            s.flush()
            s.add(NormalizedPost(source_type=SourceType.COMPETITOR, source_id=cp.id, normalized_at=now))
    return cid


def _add_competitor_posts(competitor_id: int, start_i: int, n_more: int) -> None:
    from src.db.models import CompetitorPost
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.db.session import session_scope

    now = datetime.now(UTC)
    with session_scope() as s:
        for i in range(start_i, start_i + n_more):
            cp = CompetitorPost(
                competitor_id=competitor_id, tg_message_id=1000 + i,
                posted_at=now - timedelta(days=i), text=f"deal number {i}",
                collected_at=now,
            )
            s.add(cp)
            s.flush()
            s.add(NormalizedPost(source_type=SourceType.COMPETITOR, source_id=cp.id, normalized_at=now))


_FAKE_JOB = SimpleNamespace(id=1)


def test_intel_run_upserts_without_duplicating_and_refreshes():
    from sqlalchemy import func, select
    from src.db.models_competitor_intel import CompetitorBenchmark, CompetitorProfile
    from src.db.session import session_scope
    from src.services.intelligence.competitor import (
        BENCHMARK_DIMS,
        MIN_SAMPLE_FOR_BENCHMARKS,
        CompetitorIntelligenceEngine,
    )

    cid = _seed_competitor("UpsertRivalDeals", n_posts=MIN_SAMPLE_FOR_BENCHMARKS + 5)
    engine = CompetitorIntelligenceEngine()

    r1 = engine.run(_FAKE_JOB)
    assert r1.added == 1 and r1.updated == 0

    with session_scope() as s:
        profile_count = s.scalar(
            select(func.count()).select_from(CompetitorProfile)
            .where(CompetitorProfile.competitor_id == cid)
        )
        profile = s.scalar(select(CompetitorProfile).where(CompetitorProfile.competitor_id == cid))
        first_post_count = profile.post_count
        first_computed_at = profile.computed_at
        bench_count_1 = s.scalar(
            select(func.count()).select_from(CompetitorBenchmark)
            .where(CompetitorBenchmark.competitor_id == cid)
        )
    assert profile_count == 1, "must be exactly one row per competitor, never duplicated"
    assert first_post_count == MIN_SAMPLE_FOR_BENCHMARKS + 5
    assert bench_count_1 == len(BENCHMARK_DIMS)

    # more posts land, then intel re-runs (this used to crash with
    # UNIQUE constraint failed: competitor_profiles.intel_version, competitor_id)
    _add_competitor_posts(cid, start_i=1000, n_more=3)
    r2 = engine.run(_FAKE_JOB)
    assert r2.added == 0 and r2.updated == 1, "second run must upsert, not insert a new row"

    with session_scope() as s:
        profile_count_2 = s.scalar(
            select(func.count()).select_from(CompetitorProfile)
            .where(CompetitorProfile.competitor_id == cid)
        )
        profile2 = s.scalar(select(CompetitorProfile).where(CompetitorProfile.competitor_id == cid))
        bench_count_2 = s.scalar(
            select(func.count()).select_from(CompetitorBenchmark)
            .where(CompetitorBenchmark.competitor_id == cid)
        )
    assert profile_count_2 == 1, "still exactly one row after the second run — no duplication"
    assert profile2.post_count == MIN_SAMPLE_FOR_BENCHMARKS + 5 + 3, "fields refreshed in place"
    assert profile2.computed_at >= first_computed_at
    assert bench_count_2 == len(BENCHMARK_DIMS), "benchmarks replaced, not accumulated"


def test_intel_run_skips_monitoring_disabled_competitor():
    from sqlalchemy import func, select
    from src.db.models_competitor_intel import CompetitorProfile
    from src.db.session import session_scope
    from src.services.intelligence.competitor import CompetitorIntelligenceEngine

    on_id = _seed_competitor("MonitoredRival", n_posts=25, monitoring_enabled=True)
    off_id = _seed_competitor("PausedRival", n_posts=25, monitoring_enabled=False)

    result = CompetitorIntelligenceEngine().run(_FAKE_JOB)
    assert result.processed == 1, "the disabled competitor must not even be counted as processed"

    with session_scope() as s:
        on_count = s.scalar(
            select(func.count()).select_from(CompetitorProfile).where(CompetitorProfile.competitor_id == on_id))
        off_count = s.scalar(
            select(func.count()).select_from(CompetitorProfile).where(CompetitorProfile.competitor_id == off_id))
    assert on_count == 1, "monitored competitor gets a profile"
    assert off_count == 0, "monitoring_enabled=False competitor must be skipped entirely"
