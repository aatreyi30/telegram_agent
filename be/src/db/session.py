"""Engine + session management."""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.config.settings import get_settings
from src.db.base import Base


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    settings.ensure_dirs()
    connect_args = {}
    if settings.db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(
        settings.db_url,
        echo=False,
        future=True,
        connect_args=connect_args,
    )

    if settings.db_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            # SQLite allows only ONE writer at a time. The scheduler runs many jobs in
            # parallel threads, so writers queue behind each other — busy_timeout is how
            # long a blocked writer WAITS for the lock before giving up with "database is
            # locked". 5s was too short under that concurrency; 30s lets them serialise
            # cleanly. synchronous=NORMAL (safe in WAL) skips an fsync per commit, so each
            # writer holds the lock for less time -> less contention.
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

    return engine


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session context — commit on success, rollback on error."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables. Import models first so they register on Base.metadata."""
    from src.db import models_org  # noqa: F401  (organizations/users — FK target for channels)
    from src.db import models  # noqa: F401  (registers ingestion tables)
    from src.db import models_normalization  # noqa: F401  (Phase 2 tables)
    from src.db import models_classification  # noqa: F401  (Phase 3 tables)
    from src.db import models_intelligence  # noqa: F401  (Phase 4 tables)
    from src.db import models_competitor_intel  # noqa: F401  (Phase 5 tables)
    from src.db import models_learning  # noqa: F401  (Phase 6 tables)
    from src.db import models_growth  # noqa: F401  (Phase 7 tables)
    from src.db import models_reasoning  # noqa: F401  (Phase 8 tables)
    from src.db import models_generation  # noqa: F401  (Phase 9 tables)
    from src.db import models_campaign  # noqa: F401  (Phase 10 tables)
    from src.db import models_report  # noqa: F401  (daily aggregate report rows)
    from src.db import models_automation  # noqa: F401  (Phase 11 tables)
    from src.db import models_scheduler  # noqa: F401  (scheduler run logs)
    from src.db import models_ai_output  # noqa: F401  (Phase 0.2: persisted AI outputs)
    from src.db import models_ai_trace  # noqa: F401  (per-call AI trace ledger)
    from src.db import models_prediction  # noqa: F401  (Phase 2: predict/outcome/retro tables)

    Base.metadata.create_all(get_engine())
    # create_all does not ALTER existing tables; add columns introduced after first run.
    from src.db.migrate import (
        add_missing_columns,
        backfill_channel_id,
        dedupe_and_index_campaign_plans,
        drop_removed_tables,
    )
    add_missing_columns(get_engine())
    backfill_channel_id(get_engine())  # attribute pre-multi-tenancy derived rows to a channel
    drop_removed_tables(get_engine())  # drop tables whose ORM model no longer exists
    dedupe_and_index_campaign_plans(get_engine())  # backstop the daily/weekly AI-plan cache race
