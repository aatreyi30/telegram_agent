# Telegram Agent Rescue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the product coherent — persist a day-wise `DailyChannelReport` the AI reasons over, turn AI into a grounded analyst+planner with a fact-checker and a closed feedback loop, fix the competitor pipeline, and make the UI honest about AI vs computed.

**Architecture:** Deterministic Python computes per-post rows → a nightly aggregator writes one `DailyChannelReport` row per `(channel, date, source_type)` → the AI reads report rows and emits schema-validated digests/plans whose cited numbers are fact-checked against those rows → deterministic generation fills AI-planned slots with real inventory → the next day's plan is reconciled against what actually happened. Reference spec: `save-telegram.md`.

**Tech Stack:** Python 3 / SQLAlchemy 2.0 (`Mapped`/`mapped_column`) / SQLite (`Base.metadata.create_all` + `migrate.py` additive ALTERs, no Alembic) / FastAPI / Groq Llama-3.3-70B via `AIClient` / pytest (temp-file SQLite, per-module `_isolated_db` fixture) / Next.js + axios + @tanstack/react-query.

## Global Constraints

- **Migrations:** New tables → add `from src.db import models_<name>` to `init_db()` in `be/src/db/session.py`. New columns on existing tables → add entries to the `_ADDITIONS` dict in `be/src/db/migrate.py` (nullable/defaulted only; SQLite-only path). Never write Alembic.
- **No-hallucination rule:** AI never invents a deal/price/link/number. Every number the AI emits goes in a `cited_numbers` array and is validated against the report rows it was given. AI plans *strategy*; deterministic code fills slots from real inventory.
- **IST day boundary:** Reuse `from src.services.analytics.periods import IST` and the `_ist_bounds(day)` pattern (`datetime(y,m,d,tzinfo=IST)`, `+timedelta(days=1)`). Storage is UTC; treat naive datetimes read from SQLite as UTC.
- **AI client:** Reuse `AIClient` (`be/src/ai/client.py`) unchanged. `complete(user, *, system_extra="", max_tokens=..., effort=...) -> str` returns **plain text** — there is no JSON mode, so structured output is prompted-as-JSON then parsed defensively. When no key, `available()` is False and `complete` raises `AIUnavailable` — always wrap AI calls and fall back to deterministic output.
- **Tests:** pytest from `be/`. Each new test module defines its own `_isolated_db` fixture (copy the pattern from `be/tests/test_phase1_foundation.py`): set `DB_URL`/`RAW_SNAPSHOT_DIR` to a tempdir, clear `get_settings`/`get_engine`/`get_sessionmaker` caches, call `init_db()`. Get sessions via `session_scope()`. Run: `pytest tests/<file>.py -v`.
- **Response envelope:** API handlers return `ok(data)` / `fail(msg, status)` from `src/shared/response.py`. Handlers hold no session; they call `src.controllers.service` functions that open their own `session_scope()`.
- **Versioning:** New engines/artifacts carry a `*_VERSION` int constant like the existing modules.

---

## Parallel execution waves (file ownership — prevents collisions)

Agents in the same wave touch **disjoint files**. Do not start a wave until the prior wave is reviewed and merged.

| Wave | Tasks | Owned files (exclusive) |
|---|---|---|
| **1** | T1–T3 (competitor) | `telegram_competitor.py`, `collection/scheduler.py`, `controllers/schedulers.py` |
| **1** | T4, T7, T14 (all DB schema) | `models_report.py` (new), `models_campaign.py`, `models.py`, `db/session.py`, `db/migrate.py` |
| **2** | T5 (aggregator) | `services/analytics/daily_report.py` (new) |
| **2** | T8 (context getters) | `ai/context.py` |
| **2** | T15 (discovery verifier) | `services/collection/discovery.py` |
| **3** | T9, T10, T11 (AI plan+factcheck+exec) | `ai/planner.py` (new), `ai/factcheck.py` (new), `services/generation/ai_execution.py` (new) |
| **3** | T12, T13 (closed loop) | `services/analytics/reconciliation.py` (new) |
| **4** | T6, T16 (scheduler wiring, report persistence, competitor parity) | `controllers/schedulers.py` (again — single owner), `controllers/service.py`, `routers/data.py` (T17 folded in) |
| **5** | T18–T20 (frontend) | `next/**` |

Waves 2–3 depend on Wave 1's models existing. Wave 4 depends on the aggregator + planner. Wave 5 depends on the digest route.

---

## Task 1: Fix the Telethon competitor-fetch blocker

**Files:**
- Modify: `be/src/services/collection/telegram_competitor.py` (the `async with asyncio.get_event_loop().run_in_executor(...)` at ~:104-106, and the `except` at ~:110)
- Test: `be/tests/test_competitor_fetch_fix.py` (new)

**Interfaces:**
- Consumes: existing `CompetitorTelethonFetcher` (or whatever the class is named in that file) and its `_update_from_entity(comp_id, entity)` sync method.
- Produces: the resolve/update path no longer raises `AttributeError`; on success competitors flip to `AVAILABLE`; `FloodWaitError` is caught distinctly from generic failure.

- [ ] **Step 1: Read the file to confirm exact surrounding code**

Read `be/src/services/collection/telegram_competitor.py` fully. Confirm the buggy block, the method name holding it, the class name, how `entity` is obtained, the broad `except Exception` line, and that `FloodWaitError` is imported (~:75) but never caught. Note the enclosing method's name and signature for the test.

- [ ] **Step 2: Write the failing test**

```python
# be/tests/test_competitor_fetch_fix.py
from __future__ import annotations
import os, tempfile, inspect
import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db
    init_db()
    yield


def test_no_run_in_executor_async_with():
    """The buggy `async with run_in_executor(...)` pattern must be gone."""
    import src.services.collection.telegram_competitor as mod
    src = inspect.getsource(mod)
    assert "async with asyncio.get_event_loop().run_in_executor" not in src, (
        "the Future-as-context-manager bug is still present"
    )


def test_floodwait_is_handled_distinctly():
    import src.services.collection.telegram_competitor as mod
    src = inspect.getsource(mod)
    assert "FloodWaitError" in src
    # FloodWaitError must appear in an except clause, not only the import
    assert "except FloodWaitError" in src or "except (FloodWaitError" in src
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_competitor_fetch_fix.py -v`
Expected: FAIL — `test_no_run_in_executor_async_with` asserts the bug is present.

- [ ] **Step 4: Apply the fix**

Replace the buggy block:
```python
# Mark competitor as available and update metadata
async with asyncio.get_event_loop().run_in_executor(None, self._update_from_entity, comp_id, entity):
    pass
```
with a direct synchronous call (the method manages its own `session_scope`):
```python
# Mark competitor as available and update metadata.
# _update_from_entity manages its own session_scope; call it directly —
# run_in_executor returns a Future, which is not an async context manager.
self._update_from_entity(comp_id, entity)
```

Then split the broad handler around this resolve/fetch path so flood-waits are distinct. Where the current `except Exception:` swallows everything and returns `None`, add a preceding clause (import is already at ~:75):
```python
except FloodWaitError as e:
    logger.warning("[competitor] flood-wait %ss for %s; not a Telethon failure", getattr(e, "seconds", "?"), comp_id)
    raise  # let the caller back off; do NOT fall through to the degraded t.me/s scrape
except Exception as e:
    logger.warning("[competitor] telethon fetch failed for %s: %s", comp_id, e)
    return None
```
Keep the existing return-`None` semantics for the generic case so callers still fall back to scrape only on genuine failures. Match the existing `logger` name used in the file.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_competitor_fetch_fix.py -v`
Expected: PASS (both).

- [ ] **Step 6: Commit**

```bash
git add be/src/services/collection/telegram_competitor.py be/tests/test_competitor_fetch_fix.py
git commit -m "fix(collection): competitor Telethon fetch — drop Future-as-context-manager bug, handle FloodWaitError"
```

---

## Task 2: Unify the competitor fetch path (DB + env)

**Files:**
- Modify: `be/src/services/collection/scheduler.py` (the `_competitors` tick handler)
- Test: `be/tests/test_competitor_scheduler_unify.py` (new)

**Interfaces:**
- Consumes: `Competitor` model (`src.db.models`), `settings.competitor_channels`, existing `CompetitorCollector`.
- Produces: `_competitors` iterates the **union** of env `competitor_channels` and DB `Competitor.username` rows (deduped), matching `controllers/schedulers.py:j_competitor_sync`.

- [ ] **Step 1: Read both schedulers**

Read `be/src/services/collection/scheduler.py` (`_competitors`) and `be/src/controllers/schedulers.py:72-97` (`j_competitor_sync`) to copy the exact DB-union pattern (it already does `extra = [c.username for c in s.scalars(select(Competitor)) if c.username]`, skips env dups).

- [ ] **Step 2: Write the failing test**

```python
# be/tests/test_competitor_scheduler_unify.py
from __future__ import annotations
import os, tempfile, inspect
import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    os.environ["COMPETITOR_CHANNELS"] = "EnvComp"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db
    init_db()
    yield


def test_competitors_tick_reads_db_competitors():
    """_competitors must consult the Competitor table, not only the env list."""
    import src.services.collection.scheduler as mod
    src = inspect.getsource(mod._competitors) if hasattr(mod, "_competitors") else inspect.getsource(mod)
    assert "Competitor" in src, "_competitors still ignores DB-discovered competitors"
```

(If `_competitors` is a method on a class, adjust the `getsource` target to that method.)

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_competitor_scheduler_unify.py -v`
Expected: FAIL — `Competitor` not referenced in the tick.

- [ ] **Step 4: Implement the union**

In `_competitors`, after building the env list, add DB competitors (dedup, case-insensitive on username), mirroring `j_competitor_sync`:
```python
from sqlalchemy import select
from src.db.models import Competitor
from src.db.session import session_scope

usernames = list(self.settings.competitor_channels)
seen = {u.lstrip("@").lower() for u in usernames}
with session_scope() as s:
    for c in s.scalars(select(Competitor)):
        if c.username and c.username.lstrip("@").lower() not in seen:
            usernames.append(c.username)
            seen.add(c.username.lstrip("@").lower())
# ... then iterate `usernames` through CompetitorCollector as before
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_competitor_scheduler_unify.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add be/src/services/collection/scheduler.py be/tests/test_competitor_scheduler_unify.py
git commit -m "fix(collection): CollectionScheduler fetches DB-discovered competitors, not only env list"
```

---

## Task 3: Decouple discovery from intel (ordering bug)

**Files:**
- Modify: `be/src/controllers/schedulers.py` (`j_competitor_intel`)
- Test: `be/tests/test_competitor_intel_ordering.py` (new)

**Interfaces:**
- Consumes: `discover_competitors`, `CompetitorIntelligenceEngine`.
- Produces: `j_competitor_intel` no longer calls `discover_competitors` in the same tick as profiling. Discovery moves to its own job function `j_competitor_discover()` registered on its own cadence; intel runs only over competitors that already have collected posts.

- [ ] **Step 1: Read the current job + registry**

Read `be/src/controllers/schedulers.py:146-156` (`j_competitor_intel`) and how jobs are registered (`SchedulerRegistry`, the `CronTrigger`/`IntervalTrigger` wiring near the bottom of the file). Note the registration list/structure so a new job slots in.

- [ ] **Step 2: Write the failing test**

```python
# be/tests/test_competitor_intel_ordering.py
from __future__ import annotations
import inspect
import src.controllers.schedulers as sched


def test_intel_does_not_discover_in_same_tick():
    src = inspect.getsource(sched.j_competitor_intel)
    assert "discover_competitors" not in src, (
        "discovery must not run in the same tick as profiling"
    )


def test_discovery_job_exists():
    assert hasattr(sched, "j_competitor_discover"), "discovery needs its own job function"
    src = inspect.getsource(sched.j_competitor_discover)
    assert "discover_competitors" in src
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_competitor_intel_ordering.py -v`
Expected: FAIL — `discover_competitors` still in `j_competitor_intel`, no `j_competitor_discover`.

- [ ] **Step 4: Split the jobs**

Add a dedicated discovery job and strip discovery out of intel:
```python
def j_competitor_discover() -> dict:
    """Discover new competitor channels. Runs on its own cadence, ahead of sync,
    so newly added competitors get their posts collected by j_competitor_sync
    before j_competitor_intel profiles them (fixes the same-tick ordering bug)."""
    from src.services.collection.discovery import discover_competitors
    added = discover_competitors(max_add=5).get("added", 0)
    return {"added": added}


def j_competitor_intel() -> dict:
    # profile ONLY over competitors that already have collected posts
    from src.services.intelligence.competitor import CompetitorIntelligenceEngine
    n = _run_engine(CompetitorIntelligenceEngine(), "competitor-intel")
    return {"processed": n}
```
Register `j_competitor_discover` in the `SchedulerRegistry` on a daily cron that fires **before** the 07:00 intel job (e.g. `CronTrigger(hour=6, minute=0)`), so the 10-min `j_competitor_sync` collects posts in between. Match the exact registration idiom already used in the file.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_competitor_intel_ordering.py -v`
Expected: PASS (both).

- [ ] **Step 6: Commit**

```bash
git add be/src/controllers/schedulers.py be/tests/test_competitor_intel_ordering.py
git commit -m "fix(scheduler): split competitor discovery from intel to fix same-tick ordering bug"
```

---

## Task 4: `DailyChannelReport` model + registration + migration

**Files:**
- Create: `be/src/db/models_report.py`
- Modify: `be/src/db/session.py` (add import in `init_db()`)
- Test: `be/tests/test_daily_report_model.py` (new)

**Interfaces:**
- Produces: `DailyChannelReport` ORM class + `ReportSourceType` (`OWNED`/`COMPETITOR`) + `REPORT_VERSION`. Columns exactly as in spec §2.1. Consumed by Tasks 5, 8, 13, 16.

- [ ] **Step 1: Write the failing test**

```python
# be/tests/test_daily_report_model.py
from __future__ import annotations
import os, tempfile
from datetime import date, datetime, timezone
import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db
    init_db()
    yield


def test_report_row_roundtrip_and_uniqueness():
    from src.db.models_report import DailyChannelReport, ReportSourceType
    from src.db.session import session_scope
    from sqlalchemy import select
    with session_scope() as s:
        s.add(DailyChannelReport(
            channel_id=None, source_type=ReportSourceType.OWNED,
            report_date=date(2026, 7, 6),
            posts_count=6, deals_posted=5, merchants_featured=3,
            views_total=12000, views_avg=2000.0, views_median=1900.0,
            views_max=4000, views_min=800,
            reactions_total=120, forwards_total=45, engagement_rate=0.013,
            subs_start=1000, subs_end=1010, subs_net=10,
            type_mix={"single": 4, "collection": 2},
            category_mix={"electronics": 3, "fashion": 2},
            posting_hours={"12": 2, "19": 2},
            best_category="electronics", worst_category="fashion",
            computed_at=datetime.now(timezone.utc), data_completeness=1.0,
        ))
    with session_scope() as s:
        row = s.scalars(select(DailyChannelReport)).one()
        assert row.views_max == 4000
        assert row.type_mix["single"] == 4
        assert row.source_type == ReportSourceType.OWNED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_daily_report_model.py -v`
Expected: FAIL — `ModuleNotFoundError: src.db.models_report`.

- [ ] **Step 3: Create the model**

```python
# be/src/db/models_report.py
"""Day-wise aggregate report row — the compact artifact the AI reasons over.

One row per (channel_id, report_date, source_type). Computed nightly by a
deterministic aggregator (services/analytics/daily_report.py) from per-post rows
+ metric snapshots. Applies to owned AND competitor channels (source_type), so
the AI compares on identical footing. Persisting this is the single most
important wiring fix: yesterday's actuals now reach today's plan.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, TimestampMixin

REPORT_VERSION = 1


class ReportSourceType:
    OWNED = "owned"
    COMPETITOR = "competitor"


class DailyChannelReport(Base, TimestampMixin):
    __tablename__ = "daily_channel_reports"
    __table_args__ = (
        UniqueConstraint("channel_id", "report_date", "source_type", name="uq_daily_report"),
        Index("ix_daily_report_date", "report_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_version: Mapped[int] = mapped_column(Integer, default=REPORT_VERSION)

    # volume
    posts_count: Mapped[int] = mapped_column(Integer, default=0)
    deals_posted: Mapped[int] = mapped_column(Integer, default=0)
    merchants_featured: Mapped[int] = mapped_column(Integer, default=0)

    # views
    views_total: Mapped[int] = mapped_column(Integer, default=0)
    views_avg: Mapped[float] = mapped_column(Float, default=0.0)
    views_median: Mapped[float] = mapped_column(Float, default=0.0)
    views_max: Mapped[int] = mapped_column(Integer, default=0)
    views_min: Mapped[int] = mapped_column(Integer, default=0)
    top_post_id: Mapped[int | None] = mapped_column(Integer)      # tg message id / post id
    bottom_post_id: Mapped[int | None] = mapped_column(Integer)

    # engagement
    reactions_total: Mapped[int] = mapped_column(Integer, default=0)
    forwards_total: Mapped[int] = mapped_column(Integer, default=0)
    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0)

    # audience
    subs_start: Mapped[int | None] = mapped_column(Integer)
    subs_end: Mapped[int | None] = mapped_column(Integer)
    subs_net: Mapped[int | None] = mapped_column(Integer)

    # composition
    type_mix: Mapped[dict | None] = mapped_column(JSON)
    category_mix: Mapped[dict | None] = mapped_column(JSON)
    posting_hours: Mapped[dict | None] = mapped_column(JSON)
    best_category: Mapped[str | None] = mapped_column(String(64))
    worst_category: Mapped[str | None] = mapped_column(String(64))

    # provenance
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_completeness: Mapped[float] = mapped_column(Float, default=1.0)
```

- [ ] **Step 4: Register in `init_db()`**

In `be/src/db/session.py`, inside `init_db()`, add alongside the other model imports (after `models_campaign`):
```python
    from src.db import models_report  # noqa: F401  (daily aggregate report rows)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_daily_report_model.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add be/src/db/models_report.py be/src/db/session.py be/tests/test_daily_report_model.py
git commit -m "feat(db): add DailyChannelReport model (day-wise aggregate report spine)"
```

---

## Task 7: Extend `CampaignPlan` with AI + fact-check + closed-loop columns

**Files:**
- Modify: `be/src/db/models_campaign.py` (add columns to `CampaignPlan`)
- Modify: `be/src/db/migrate.py` (add entries to `_ADDITIONS`)
- Test: `be/tests/test_campaign_plan_columns.py` (new)

**Interfaces:**
- Produces: `CampaignPlan` gains `ai_digest` (Text), `cited_numbers` (JSON), `factcheck_status` (String), `is_ai_generated` (Boolean), `report_ids` (JSON), `adherence` (JSON), `reconciliation` (JSON). Consumed by Tasks 9, 10, 13, 17.

- [ ] **Step 1: Read `migrate.py` `_ADDITIONS` shape**

Read `be/src/db/migrate.py` to copy the exact structure of the `_ADDITIONS` dict (table name → list of `(column_name, column_sql_type)` or however it is keyed) and the ALTER idiom.

- [ ] **Step 2: Write the failing test**

```python
# be/tests/test_campaign_plan_columns.py
from __future__ import annotations
import os, tempfile
from datetime import date, datetime, timezone
import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db
    init_db()
    yield


def test_campaign_plan_new_columns_roundtrip():
    from src.db.models_campaign import CampaignPlan, PlanType
    from src.db.session import session_scope
    from sqlalchemy import select
    with session_scope() as s:
        s.add(CampaignPlan(
            plan_type=PlanType.DAILY, title="AI day plan",
            target_date=date(2026, 7, 8), blueprint={"post_slots": []},
            expected_outcome={"electronics_views_pct": 15},
            confidence=0.6, generated_at=datetime.now(timezone.utc),
            ai_digest="Yesterday views up 12%.", cited_numbers=[2100, 980, 0.30],
            factcheck_status="passed", is_ai_generated=True,
            report_ids=[1, 2], adherence={"planned": 6, "published": 4},
            reconciliation={"note": "2 evening slots missed"},
        ))
    with session_scope() as s:
        p = s.scalars(select(CampaignPlan)).one()
        assert p.is_ai_generated is True
        assert p.factcheck_status == "passed"
        assert p.cited_numbers == [2100, 980, 0.30]
        assert p.adherence["published"] == 4
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_campaign_plan_columns.py -v`
Expected: FAIL — unexpected keyword argument `ai_digest`.

- [ ] **Step 4: Add the columns to the model**

In `be/src/db/models_campaign.py`, append to `CampaignPlan` (after `generated_at`):
```python
    # --- AI analyst/planner provenance (rescue plan §2.5) ---
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_digest: Mapped[str | None] = mapped_column(Text)
    cited_numbers: Mapped[list | None] = mapped_column(JSON)
    factcheck_status: Mapped[str | None] = mapped_column(String(16))  # passed|failed|skipped
    report_ids: Mapped[list | None] = mapped_column(JSON)             # DailyChannelReport ids fed to the model
    # --- closed-loop feedback (§3.5) ---
    adherence: Mapped[dict | None] = mapped_column(JSON)              # planned vs published (deterministic)
    reconciliation: Mapped[dict | None] = mapped_column(JSON)         # expected-vs-actual + AI summary
```
(`Boolean`, `Text`, `JSON`, `String` are already imported in this file.)

- [ ] **Step 5: Register additive columns in `migrate.py`**

Add to `_ADDITIONS` in `be/src/db/migrate.py` (use the file's existing key/type idiom; SQLite types):
```python
    "campaign_plans": [
        ("is_ai_generated", "BOOLEAN DEFAULT 0"),
        ("ai_digest", "TEXT"),
        ("cited_numbers", "JSON"),
        ("factcheck_status", "VARCHAR(16)"),
        ("report_ids", "JSON"),
        ("adherence", "JSON"),
        ("reconciliation", "JSON"),
    ],
```
If `_ADDITIONS` already has a `"campaign_plans"` key, merge into it instead of adding a duplicate key.

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_campaign_plan_columns.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add be/src/db/models_campaign.py be/src/db/migrate.py be/tests/test_campaign_plan_columns.py
git commit -m "feat(db): extend CampaignPlan with AI + fact-check + closed-loop columns"
```

---

## Task 14: Extend `Competitor` with resolution provenance columns

**Files:**
- Modify: `be/src/db/models.py` (`Competitor` at ~:293)
- Modify: `be/src/db/migrate.py` (`_ADDITIONS`)
- Test: `be/tests/test_competitor_columns.py` (new)

**Interfaces:**
- Produces: `Competitor` gains `resolution_confidence` (Float) + `verified_by` (String: `heuristic`/`ai`/`manual`). Consumed by Task 15.

- [ ] **Step 1: Write the failing test**

```python
# be/tests/test_competitor_columns.py
from __future__ import annotations
import os, tempfile
import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db
    init_db()
    yield


def test_competitor_resolution_columns():
    from src.db.models import Competitor
    from src.db.session import session_scope
    from sqlalchemy import select
    with session_scope() as s:
        s.add(Competitor(username="SomeBrand", title="Some Brand",
                         resolution_confidence=0.82, verified_by="ai"))
    with session_scope() as s:
        c = s.scalars(select(Competitor)).one()
        assert c.resolution_confidence == 0.82
        assert c.verified_by == "ai"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_competitor_columns.py -v`
Expected: FAIL — unexpected keyword argument `resolution_confidence`.

- [ ] **Step 3: Add columns + migration**

In `be/src/db/models.py`, add to `Competitor`:
```python
    resolution_confidence: Mapped[float | None] = mapped_column(Float)
    verified_by: Mapped[str | None] = mapped_column(String(16))  # heuristic|ai|manual
```
(Confirm `Float`/`String` are imported at the top of `models.py`; they are used elsewhere in the file.)

In `be/src/db/migrate.py` `_ADDITIONS`:
```python
    "competitors": [
        ("resolution_confidence", "FLOAT"),
        ("verified_by", "VARCHAR(16)"),
    ],
```
(Merge if `"competitors"` already keyed.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_competitor_columns.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add be/src/db/models.py be/src/db/migrate.py be/tests/test_competitor_columns.py
git commit -m "feat(db): add resolution_confidence + verified_by to Competitor"
```

---

## Task 5: Daily report aggregator

**Files:**
- Create: `be/src/services/analytics/daily_report.py`
- Test: `be/tests/test_daily_report_aggregator.py` (new)

**Interfaces:**
- Consumes: `DailyChannelReport`, `ReportSourceType`, `REPORT_VERSION` (Task 4); `day.py:summarize()`; `Post`/`Channel`/`ChannelStatSnapshot`/`NormalizedPost`.
- Produces:
  - `build_owned_report(s: Session, day: date, channel_id: int | None = None) -> DailyChannelReport` — pure builder, returns an **unpersisted** instance.
  - `persist_report(s: Session, report: DailyChannelReport) -> DailyChannelReport` — upsert on `(channel_id, report_date, source_type)`.
  - `run_daily_reports(s: Session, day: date | None = None) -> dict` — builds+persists owned (and, when available, per-competitor) reports for `day`; returns `{"owned": int, "competitor": int, "date": str}`.

- [ ] **Step 1: Write the failing test**

```python
# be/tests/test_daily_report_aggregator.py
from __future__ import annotations
import os, tempfile
from datetime import date, datetime, timezone
import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    os.environ["OWNED_CHANNELS"] = "MyChannel"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db, session_scope
    from src.db.models import Channel, Post
    init_db()
    # seed one owned channel + posts on an IST day
    from src.services.analytics.periods import IST
    from datetime import timedelta
    d = date(2026, 7, 6)
    base = datetime(d.year, d.month, d.day, 12, 0, tzinfo=IST).astimezone(timezone.utc)
    with session_scope() as s:
        ch = Channel(tg_channel_id=111, username="MyChannel", title="Mine", kind="owned")
        s.add(ch); s.flush()
        for i, v in enumerate([800, 4000, 1500]):
            s.add(Post(channel_id=ch.id, tg_message_id=1000 + i,
                       posted_at=base + timedelta(minutes=i), views=v,
                       reactions_total=10 * i, forwards=i, text=f"deal {i}"))
    yield


def test_build_owned_report_totals():
    from src.services.analytics.daily_report import build_owned_report
    from src.db.session import session_scope
    with session_scope() as s:
        rep = build_owned_report(s, date(2026, 7, 6))
        assert rep.posts_count == 3
        assert rep.views_total == 6300
        assert rep.views_max == 4000
        assert rep.views_min == 800


def test_run_daily_reports_persists_and_upserts():
    from src.services.analytics.daily_report import run_daily_reports
    from src.db.models_report import DailyChannelReport
    from src.db.session import session_scope
    from sqlalchemy import select, func
    with session_scope() as s:
        run_daily_reports(s, date(2026, 7, 6))
    with session_scope() as s:
        run_daily_reports(s, date(2026, 7, 6))  # second run must upsert, not duplicate
        n = s.scalar(select(func.count()).select_from(DailyChannelReport))
        assert n == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_daily_report_aggregator.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the aggregator**

Build on `day.py:summarize()` where possible, but compute the numeric fields directly from owned `Post` rows for the IST day so totals are exact and testable.
```python
# be/src/services/analytics/daily_report.py
"""Deterministic day-wise aggregator — persists DailyChannelReport rows.

Owned reports are computed directly from Post rows for the IST day. day.py's
summarize() is reused for composition context, but the numeric spine here is
independent and exact so it is testable and stable.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from statistics import fmean, median

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Channel, Post
from src.db.models_report import DailyChannelReport, REPORT_VERSION, ReportSourceType
from src.services.analytics.periods import IST


def _ist_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=IST)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def _owned_channel(s: Session) -> Channel | None:
    return s.scalars(
        select(Channel).where(Channel.kind == "owned").order_by(Channel.participants_count.desc())
    ).first() or s.scalars(select(Channel)).first()


def build_owned_report(s: Session, day: date, channel_id: int | None = None) -> DailyChannelReport:
    start, end = _ist_bounds(day)
    ch = None
    if channel_id is None:
        ch = _owned_channel(s)
        channel_id = ch.id if ch else None
    q = select(Post).where(Post.posted_at >= start, Post.posted_at < end)
    if channel_id is not None:
        q = q.where(Post.channel_id == channel_id)
    posts = list(s.scalars(q))

    views = [p.views or 0 for p in posts]
    reactions = sum(p.reactions_total or 0 for p in posts)
    forwards = sum(p.forwards or 0 for p in posts)
    views_total = sum(views)
    top = max(posts, key=lambda p: p.views or 0, default=None)
    bottom = min(posts, key=lambda p: p.views or 0, default=None)
    hours = Counter(str(p.posted_at.astimezone(IST).hour) for p in posts if p.posted_at)

    rep = DailyChannelReport(
        channel_id=channel_id, source_type=ReportSourceType.OWNED,
        report_date=day, report_version=REPORT_VERSION,
        posts_count=len(posts),
        deals_posted=sum(1 for p in posts if (p.text or "").strip()),
        merchants_featured=0,  # refined below from summarize() when available
        views_total=views_total,
        views_avg=round(fmean(views), 2) if views else 0.0,
        views_median=round(median(views), 2) if views else 0.0,
        views_max=max(views) if views else 0,
        views_min=min(views) if views else 0,
        top_post_id=(top.tg_message_id if top else None),
        bottom_post_id=(bottom.tg_message_id if bottom else None),
        reactions_total=reactions, forwards_total=forwards,
        engagement_rate=round((reactions + forwards) / views_total, 4) if views_total else 0.0,
        posting_hours=dict(hours),
        computed_at=datetime.now(timezone.utc),
        data_completeness=1.0,
    )
    # enrich composition + subs + merchants from summarize()/snapshots (best-effort)
    try:
        from src.services.analytics.day import summarize
        summ = summarize(s, day)
        if summ.get("available"):
            rep.type_mix = {t: c for t, c in summ.get("type_mix", [])}
            rep.category_mix = {m: c for m, c in summ.get("merchant_mix", [])}
            rep.merchants_featured = len(summ.get("merchants", []))
            merchants = summ.get("merchants", [])
            if merchants:
                rep.best_category = max(merchants, key=lambda m: m.get("total_views", 0))["key"]
                rep.worst_category = min(merchants, key=lambda m: m.get("total_views", 0))["key"]
    except Exception:
        pass
    _fill_subs(s, rep, channel_id, day)
    return rep


def _fill_subs(s: Session, rep: DailyChannelReport, channel_id: int | None, day: date) -> None:
    """subs_start/end/net from ChannelStatSnapshot when present; else NULL."""
    try:
        from src.db.models import ChannelStatSnapshot
        start, end = _ist_bounds(day)
        snaps = list(s.scalars(
            select(ChannelStatSnapshot)
            .where(ChannelStatSnapshot.channel_id == channel_id,
                   ChannelStatSnapshot.captured_at >= start,
                   ChannelStatSnapshot.captured_at < end)
            .order_by(ChannelStatSnapshot.captured_at)
        ))
        if snaps:
            rep.subs_start = snaps[0].participants_count
            rep.subs_end = snaps[-1].participants_count
            rep.subs_net = (rep.subs_end or 0) - (rep.subs_start or 0)
    except Exception:
        pass


def persist_report(s: Session, report: DailyChannelReport) -> DailyChannelReport:
    existing = s.scalars(
        select(DailyChannelReport).where(
            DailyChannelReport.channel_id == report.channel_id,
            DailyChannelReport.report_date == report.report_date,
            DailyChannelReport.source_type == report.source_type,
        )
    ).first()
    if existing is None:
        s.add(report)
        s.flush()
        return report
    for col in report.__table__.columns.keys():
        if col in ("id", "created_at", "channel_id", "report_date", "source_type"):
            continue
        setattr(existing, col, getattr(report, col))
    s.flush()
    return existing


def run_daily_reports(s: Session, day: date | None = None) -> dict:
    if day is None:
        from src.services.analytics.day import latest_owned_date
        day = latest_owned_date(s)
    if day is None:
        return {"owned": 0, "competitor": 0, "date": None}
    persist_report(s, build_owned_report(s, day))
    comp = _build_competitor_reports(s, day)
    return {"owned": 1, "competitor": comp, "date": day.isoformat()}


def _build_competitor_reports(s: Session, day: date) -> int:
    """Per-competitor daily reports from CompetitorPost cumulative views.
    Shallower than owned (no forwards/reactions guaranteed); data_completeness < 1."""
    from src.db.models import Competitor, CompetitorPost
    start, end = _ist_bounds(day)
    n = 0
    for c in s.scalars(select(Competitor)):
        posts = list(s.scalars(
            select(CompetitorPost).where(
                CompetitorPost.competitor_id == c.id,
                CompetitorPost.posted_at >= start,
                CompetitorPost.posted_at < end,
            )
        ))
        if not posts:
            continue
        views = [p.views or 0 for p in posts]
        rep = DailyChannelReport(
            channel_id=None, source_type=ReportSourceType.COMPETITOR,
            report_date=day, report_version=REPORT_VERSION,
            posts_count=len(posts), deals_posted=len(posts), merchants_featured=0,
            views_total=sum(views),
            views_avg=round(fmean(views), 2) if views else 0.0,
            views_median=round(median(views), 2) if views else 0.0,
            views_max=max(views) if views else 0, views_min=min(views) if views else 0,
            reactions_total=0, forwards_total=0, engagement_rate=0.0,
            computed_at=datetime.now(timezone.utc), data_completeness=0.6,
        )
        # store competitor identity in category_mix so reports stay keyable without a channel row
        rep.category_mix = {"_competitor": c.username or str(c.id)}
        persist_report(s, rep)
        n += 1
    return n
```
> **Adjust field names to the real schema.** Before finalizing, verify `Post` has `tg_message_id`, `reactions_total`, `forwards`, `views`, `posted_at`, `channel_id`; `Channel` has `kind`, `participants_count`; `ChannelStatSnapshot` has `participants_count`, `captured_at`; `CompetitorPost` has `competitor_id`, `posted_at`, `views`. Fix any mismatch (the exploration confirmed `Post` and `CompetitorPost` fields; double-check `ChannelStatSnapshot`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_daily_report_aggregator.py -v`
Expected: PASS (both). If `ChannelStatSnapshot` column names differ, fix `_fill_subs` and re-run.

- [ ] **Step 5: Commit**

```bash
git add be/src/services/analytics/daily_report.py be/tests/test_daily_report_aggregator.py
git commit -m "feat(analytics): daily report aggregator (owned + competitor DailyChannelReport)"
```

---

## Task 6: Wire nightly report persistence into the scheduler

**Files:**
- Modify: `be/src/controllers/schedulers.py` (add `j_daily_report` job + registration)
- Test: `be/tests/test_daily_report_job.py` (new)

**Interfaces:**
- Consumes: `run_daily_reports` (Task 5).
- Produces: `j_daily_report() -> dict` registered on a nightly cron (after collection/analytics, before AI planning). Returns `run_daily_reports`'s dict.

- [ ] **Step 1: Write the failing test**

```python
# be/tests/test_daily_report_job.py
import src.controllers.schedulers as sched


def test_daily_report_job_exists():
    assert hasattr(sched, "j_daily_report")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_daily_report_job.py -v`
Expected: FAIL — no `j_daily_report`.

- [ ] **Step 3: Add + register the job**

```python
def j_daily_report() -> dict:
    """Persist yesterday's DailyChannelReport rows (owned + competitor)."""
    from src.db.session import session_scope
    from src.services.analytics.daily_report import run_daily_reports
    with session_scope() as s:
        return run_daily_reports(s)  # defaults to latest owned date
```
Register on a nightly cron that runs after analytics collection and before the AI planning job (e.g. `CronTrigger(hour=5, minute=45)` if analytics is ~05:30). Match the file's registration idiom.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_daily_report_job.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add be/src/controllers/schedulers.py be/tests/test_daily_report_job.py
git commit -m "feat(scheduler): nightly job persists DailyChannelReport rows"
```

---

## Task 8: Report-row getters in `ai/context.py`

**Files:**
- Modify: `be/src/ai/context.py`
- Test: `be/tests/test_context_report_getters.py` (new)

**Interfaces:**
- Consumes: `DailyChannelReport`, `ReportSourceType` (Task 4).
- Produces:
  - `daily_reports(s, days: int = 8, source_type: str = ReportSourceType.OWNED) -> list[dict]` — latest N owned report rows as plain dicts (all report columns), newest first.
  - `report_baseline(s, days: int = 30) -> dict` — trailing mean of the numeric columns for owned reports.
  - `planning_context(s) -> dict` — `{reports, baseline, competitor_reports, channel, channel_style, post_type_performance}` bundle the planner consumes.

- [ ] **Step 1: Write the failing test**

```python
# be/tests/test_context_report_getters.py
from __future__ import annotations
import os, tempfile
from datetime import date, datetime, timezone
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
    from src.db.models_report import DailyChannelReport, ReportSourceType
    init_db()
    with session_scope() as s:
        for i, v in enumerate([1000, 2000, 3000]):
            s.add(DailyChannelReport(
                channel_id=None, source_type=ReportSourceType.OWNED,
                report_date=date(2026, 7, 4 + i), posts_count=5,
                views_total=v, views_avg=float(v / 5), views_max=v, views_min=100,
                computed_at=datetime.now(timezone.utc), data_completeness=1.0))
    yield


def test_daily_reports_newest_first():
    from src.ai.context import daily_reports
    from src.db.session import session_scope
    with session_scope() as s:
        rows = daily_reports(s, days=8)
        assert len(rows) == 3
        assert rows[0]["report_date"] == "2026-07-06"
        assert rows[0]["views_total"] == 3000


def test_report_baseline_mean():
    from src.ai.context import report_baseline
    from src.db.session import session_scope
    with session_scope() as s:
        b = report_baseline(s, days=30)
        assert b["views_total"] == 2000  # mean of 1000,2000,3000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_context_report_getters.py -v`
Expected: FAIL — `daily_reports` not defined.

- [ ] **Step 3: Implement the getters**

Append to `be/src/ai/context.py`:
```python
from datetime import date as _date

_REPORT_NUMERIC = (
    "posts_count", "deals_posted", "merchants_featured", "views_total",
    "views_avg", "views_median", "views_max", "views_min",
    "reactions_total", "forwards_total", "engagement_rate", "subs_net",
)


def _report_to_dict(r) -> dict:
    return {
        "report_date": r.report_date.isoformat() if r.report_date else None,
        "source_type": r.source_type,
        "posts_count": r.posts_count, "deals_posted": r.deals_posted,
        "merchants_featured": r.merchants_featured,
        "views_total": r.views_total, "views_avg": r.views_avg,
        "views_median": r.views_median, "views_max": r.views_max, "views_min": r.views_min,
        "reactions_total": r.reactions_total, "forwards_total": r.forwards_total,
        "engagement_rate": r.engagement_rate,
        "subs_start": r.subs_start, "subs_end": r.subs_end, "subs_net": r.subs_net,
        "type_mix": r.type_mix, "category_mix": r.category_mix, "posting_hours": r.posting_hours,
        "best_category": r.best_category, "worst_category": r.worst_category,
        "data_completeness": r.data_completeness, "id": r.id,
    }


def daily_reports(s: "Session", days: int = 8, source_type: str | None = None) -> list[dict]:
    from sqlalchemy import select
    from src.db.models_report import DailyChannelReport, ReportSourceType
    src_t = source_type or ReportSourceType.OWNED
    rows = list(s.scalars(
        select(DailyChannelReport)
        .where(DailyChannelReport.source_type == src_t)
        .order_by(DailyChannelReport.report_date.desc())
        .limit(days)
    ))
    return [_report_to_dict(r) for r in rows]


def report_baseline(s: "Session", days: int = 30) -> dict:
    rows = daily_reports(s, days=days)
    if not rows:
        return {}
    out = {}
    for k in _REPORT_NUMERIC:
        vals = [r[k] for r in rows if r.get(k) is not None]
        out[k] = round(sum(vals) / len(vals), 2) if vals else 0
    return out


def planning_context(s: "Session") -> dict:
    from src.db.models_report import ReportSourceType
    return {
        "channel": channel_overview(s),
        "reports": daily_reports(s, days=8, source_type=ReportSourceType.OWNED),
        "baseline": report_baseline(s, days=30),
        "competitor_reports": daily_reports(s, days=8, source_type=ReportSourceType.COMPETITOR),
        "channel_style": channel_style(s),
        "post_type_performance": post_type_performance(s),
    }
```
> If `context.py` does not already import `Session` for type hints, either add `from sqlalchemy.orm import Session` or keep the string annotations as written.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_context_report_getters.py -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add be/src/ai/context.py be/tests/test_context_report_getters.py
git commit -m "feat(ai): report-row getters + planning_context bundle"
```

---

## Task 15: Discovery accuracy — stricter gate + AI verifier

**Files:**
- Modify: `be/src/services/collection/discovery.py` (`resolve_username` ~:294-339)
- Test: `be/tests/test_discovery_verifier.py` (new)

**Interfaces:**
- Consumes: `AIClient` (`be/src/ai/client.py`), `Competitor` columns (Task 14).
- Produces: `verify_candidate(brand: str, candidates: list[dict]) -> tuple[str | None, float, str]` returning `(username_or_none, confidence, method)` where method ∈ `heuristic|ai`. `resolve_username` uses it and records `resolution_confidence`/`verified_by` on the stored `Competitor`.

- [ ] **Step 1: Read `discovery.py`**

Read `resolve_username` and how candidates (title/username/description/similarity/relevance) are built and how a `Competitor` is inserted. Note the exact candidate dict keys so the verifier signature matches.

- [ ] **Step 2: Write the failing test**

```python
# be/tests/test_discovery_verifier.py
from __future__ import annotations


def test_verify_candidate_falls_back_to_heuristic_without_ai(monkeypatch):
    import src.services.collection.discovery as disc
    # force AI unavailable
    from src.ai.client import AIClient
    monkeypatch.setattr(AIClient, "available", lambda self: (False, "no key"))
    cands = [
        {"username": "OfficialBrand", "title": "Brand Official", "description": "the brand", "similarity": 0.95, "relevance": 3},
        {"username": "IndiaDealsLoot", "title": "India Deals Loot", "description": "deals", "similarity": 0.2, "relevance": 1},
    ]
    username, conf, method = disc.verify_candidate("Brand", cands)
    assert username == "OfficialBrand"
    assert method == "heuristic"
    assert 0.0 <= conf <= 1.0


def test_verify_candidate_rejects_weak_only_match(monkeypatch):
    import src.services.collection.discovery as disc
    from src.ai.client import AIClient
    monkeypatch.setattr(AIClient, "available", lambda self: (False, "no key"))
    cands = [{"username": "IndiaDealsLoot", "title": "India Deals Loot",
              "description": "generic deals", "similarity": 0.15, "relevance": 1}]
    username, conf, method = disc.verify_candidate("Nykaa", cands)
    assert username is None  # weak, non-matching sole candidate is rejected, not accepted
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_discovery_verifier.py -v`
Expected: FAIL — `verify_candidate` not defined.

- [ ] **Step 4: Implement `verify_candidate` + stricter gate**

```python
def verify_candidate(brand: str, candidates: list[dict]) -> tuple[str | None, float, str]:
    """Resolve the official channel for `brand` from candidates.
    Returns (username|None, confidence 0..1, method 'heuristic'|'ai').
    Deterministic gate first; AI verifier only for ambiguous cases."""
    if not candidates:
        return None, 0.0, "heuristic"
    ranked = sorted(candidates, key=lambda c: (c.get("similarity", 0), c.get("relevance", 0)), reverse=True)
    top = ranked[0]
    sim = top.get("similarity", 0.0)
    rel = top.get("relevance", 0)
    runner = ranked[1] if len(ranked) > 1 else None

    # Strong deterministic accept
    if sim >= 0.8 and rel >= 2:
        return top["username"], round(min(0.99, sim), 2), "heuristic"
    # Clearly weak sole/lead candidate -> reject rather than blindly trust
    if sim < 0.4 and rel < 2:
        return None, round(sim, 2), "heuristic"

    # Ambiguous -> ask the LLM for a structured verdict (best-effort)
    from src.ai.client import AIClient, AIUnavailable
    ai = AIClient()
    ok, _ = ai.available()
    if ok:
        try:
            lines = "\n".join(
                f"- @{c['username']}: title={c.get('title','')!r} desc={c.get('description','')!r}"
                for c in ranked[:6]
            )
            prompt = (
                f"Which candidate Telegram channel, if any, is the OFFICIAL channel for the brand "
                f"\"{brand}\"? Consider only the given candidates.\n{lines}\n\n"
                "Reply with ONLY a compact JSON object: "
                '{"username": "<exact username or null>", "confidence": <0..1>}'
            )
            raw = ai.complete(prompt, max_tokens=120)
            import json, re
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                data = json.loads(m.group(0))
                uname = data.get("username")
                conf = float(data.get("confidence", 0.0))
                if uname and any(c["username"].lstrip("@").lower() == str(uname).lstrip("@").lower() for c in ranked):
                    match = next(c for c in ranked if c["username"].lstrip("@").lower() == str(uname).lstrip("@").lower())
                    return match["username"], round(conf, 2), "ai"
                return None, round(conf, 2), "ai"
        except (AIUnavailable, Exception):
            pass
    # AI unavailable/failed: accept the lead only if it clearly beats the runner-up
    if sim >= 0.6 and (runner is None or sim - runner.get("similarity", 0) >= 0.2):
        return top["username"], round(sim, 2), "heuristic"
    return None, round(sim, 2), "heuristic"
```
Then update `resolve_username` to call `verify_candidate`, and when it inserts/updates a `Competitor`, set `resolution_confidence=conf` and `verified_by=method`. Low-confidence (below the accept thresholds) resolves to `None` (not stored) rather than storing a wrong guess.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_discovery_verifier.py -v`
Expected: PASS (both).

- [ ] **Step 6: Commit**

```bash
git add be/src/services/collection/discovery.py be/tests/test_discovery_verifier.py
git commit -m "feat(discovery): stricter resolution gate + AI verifier with stored confidence"
```

---

## Task 9: Structured AI planner (digest + day/week plan)

**Files:**
- Create: `be/src/ai/planner.py`
- Test: `be/tests/test_ai_planner.py` (new)

**Interfaces:**
- Consumes: `AIClient`, `planning_context` (Task 8).
- Produces:
  - `PLAN_SCHEMA_KEYS` — the required keys of a day plan.
  - `parse_plan(raw: str) -> dict` — defensively parse the model's text into `{date, post_slots:[{type,window_ist,theme,why}], emphasis, watch, cited_numbers:[...]}`; raises `ValueError` on unrecoverable output.
  - `generate_day_plan(s: Session) -> dict` — build context, prompt, parse; returns `{"digest": str, "plan": dict, "report_ids": [int], "available": bool}`. On `AIUnavailable` returns `{"available": False, ...}`.

- [ ] **Step 1: Write the failing test**

```python
# be/tests/test_ai_planner.py
from __future__ import annotations
import pytest
from src.ai.planner import parse_plan


def test_parse_plan_extracts_json_block():
    raw = (
        "Here is the plan:\n"
        '{"date":"2026-07-08","post_slots":[{"type":"single","window_ist":"12:00-13:00","theme":"electronics","why":"x"}],'
        '"emphasis":"push electronics","watch":"forwards down","cited_numbers":[2100,980,0.3]}\n'
        "Hope this helps!"
    )
    plan = parse_plan(raw)
    assert plan["date"] == "2026-07-08"
    assert plan["post_slots"][0]["theme"] == "electronics"
    assert plan["cited_numbers"] == [2100, 980, 0.3]


def test_parse_plan_raises_on_garbage():
    with pytest.raises(ValueError):
        parse_plan("no json here at all")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ai_planner.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the planner**

```python
# be/src/ai/planner.py
"""AI analyst + planner. Reads DailyChannelReport rows, emits a grounded digest
+ structured day plan. AIClient has no JSON mode, so we prompt for JSON and
parse defensively; numbers are fact-checked downstream (ai/factcheck.py)."""
from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from src.ai.client import AIClient, AIUnavailable
from src.ai.context import planning_context, to_json

PLAN_SCHEMA_KEYS = ("date", "post_slots", "emphasis", "watch", "cited_numbers")

_PLAN_INSTRUCTIONS = (
    "You are the channel's daily analyst and planner. You are given recent daily "
    "report rows (facts) and a trailing baseline. Do two things:\n"
    "1) Write a 3-4 sentence DIGEST: how yesterday went vs baseline, and today's focus.\n"
    "2) Produce a DAY PLAN as JSON.\n\n"
    "HARD RULES:\n"
    "- Use ONLY numbers that appear in the DATA. Never invent a number.\n"
    "- Put every number you cite into cited_numbers.\n"
    "- Do not invent deals, prices, links, or merchants.\n\n"
    "Output EXACTLY:\n"
    "First the digest paragraph, then on a new line the token ===PLAN=== , then a JSON object:\n"
    '{"date":"YYYY-MM-DD","post_slots":[{"type":"single|collection","window_ist":"HH:MM-HH:MM",'
    '"theme":"<category>","why":"<short>"}],"emphasis":"<one line>","watch":"<one line>",'
    '"cited_numbers":[<numbers you used>]}'
)


def parse_plan(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("no JSON object found in model output")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"plan JSON invalid: {e}") from e
    data.setdefault("post_slots", [])
    data.setdefault("cited_numbers", [])
    if not isinstance(data.get("post_slots"), list):
        raise ValueError("post_slots must be a list")
    return data


def _split_digest_and_plan(raw: str) -> tuple[str, str]:
    if "===PLAN===" in raw:
        digest, _, plan = raw.partition("===PLAN===")
        return digest.strip(), plan.strip()
    # fallback: digest is everything before the first '{'
    idx = raw.find("{")
    return (raw[:idx].strip() if idx > 0 else ""), raw[idx:] if idx >= 0 else raw


def generate_day_plan(s: Session) -> dict:
    ctx = planning_context(s)
    if not ctx.get("reports"):
        return {"available": False, "reason": "no report rows yet", "plan": None, "digest": ""}
    report_ids = [r["id"] for r in ctx["reports"] if r.get("id") is not None]
    ai = AIClient()
    try:
        user = f"{_PLAN_INSTRUCTIONS}\n\nDATA:\n{to_json(ctx)}"
        raw = ai.complete(user, max_tokens=1500)
    except AIUnavailable as e:
        return {"available": False, "reason": str(e), "plan": None, "digest": ""}
    digest, plan_text = _split_digest_and_plan(raw)
    try:
        plan = parse_plan(plan_text)
    except ValueError:
        return {"available": False, "reason": "unparseable plan", "plan": None, "digest": digest}
    return {"available": True, "digest": digest, "plan": plan, "report_ids": report_ids}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ai_planner.py -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add be/src/ai/planner.py be/tests/test_ai_planner.py
git commit -m "feat(ai): structured analyst+planner (digest + day plan JSON)"
```

---

## Task 10: Fact-checker for `cited_numbers`

**Files:**
- Create: `be/src/ai/factcheck.py`
- Test: `be/tests/test_ai_factcheck.py` (new)

**Interfaces:**
- Produces: `check_cited_numbers(cited: list[float], reports: list[dict], *, tolerance: float = 0.02) -> dict` returning `{"status": "passed"|"failed", "unverified": [numbers not found]}`. A number verifies if it (within tolerance, or exact for ints) appears among any numeric value in the given report dicts.

- [ ] **Step 1: Write the failing test**

```python
# be/tests/test_ai_factcheck.py
from src.ai.factcheck import check_cited_numbers


def _reports():
    return [{"views_total": 2100, "forwards_total": 980, "engagement_rate": 0.30, "views_max": 4000}]


def test_all_cited_numbers_present_passes():
    res = check_cited_numbers([2100, 980, 0.30], _reports())
    assert res["status"] == "passed"
    assert res["unverified"] == []


def test_fabricated_number_fails():
    res = check_cited_numbers([2100, 9999], _reports())
    assert res["status"] == "failed"
    assert 9999 in res["unverified"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ai_factcheck.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the fact-checker**

```python
# be/src/ai/factcheck.py
"""Deterministic guard: every number the AI cited must appear in the report
rows it was given. Closes the prompt-only 'no hallucinated numbers' gap."""
from __future__ import annotations


def _numeric_values(reports: list[dict]) -> list[float]:
    vals: list[float] = []
    for r in reports:
        for v in r.values():
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                vals.append(float(v))
            elif isinstance(v, dict):
                vals.extend(float(x) for x in v.values() if isinstance(x, (int, float)) and not isinstance(x, bool))
    return vals


def _matches(target: float, pool: list[float], tolerance: float) -> bool:
    for v in pool:
        if target == v:
            return True
        denom = abs(v) if v else 1.0
        if abs(target - v) / denom <= tolerance:
            return True
    return False


def check_cited_numbers(cited: list[float], reports: list[dict], *, tolerance: float = 0.02) -> dict:
    pool = _numeric_values(reports)
    unverified = [c for c in (cited or []) if isinstance(c, (int, float)) and not _matches(float(c), pool, tolerance)]
    return {"status": "failed" if unverified else "passed", "unverified": unverified}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ai_factcheck.py -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add be/src/ai/factcheck.py be/tests/test_ai_factcheck.py
git commit -m "feat(ai): fact-checker validates cited_numbers against report rows"
```

---

## Task 11: Persist plan + execute AI slots against real inventory

**Files:**
- Create: `be/src/services/generation/ai_execution.py`
- Test: `be/tests/test_ai_execution.py` (new)

**Interfaces:**
- Consumes: `generate_day_plan` (T9), `check_cited_numbers` (T10), `CampaignPlan` columns (T7), `daily_planner.build_and_schedule_day` (existing).
- Produces:
  - `persist_ai_plan(s, result: dict) -> CampaignPlan | None` — writes a `CampaignPlan` (is_ai_generated=True, blueprint=plan, ai_digest, cited_numbers, factcheck_status, report_ids). Skips persisting the plan's numbers as trusted if factcheck failed (still stores with `factcheck_status="failed"`).
  - `run_ai_daily(s) -> dict` — orchestrates generate → factcheck → persist → (best-effort) `build_and_schedule_day`. Returns a summary dict.

- [ ] **Step 1: Write the failing test**

```python
# be/tests/test_ai_execution.py
from __future__ import annotations
import os, tempfile
from datetime import date, datetime, timezone
import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db
    init_db()
    yield


def test_persist_ai_plan_writes_flagged_row():
    from src.services.generation.ai_execution import persist_ai_plan
    from src.db.models_campaign import CampaignPlan
    from src.db.session import session_scope
    from sqlalchemy import select
    result = {
        "available": True,
        "digest": "Views up 12% vs baseline.",
        "plan": {"date": "2026-07-08", "post_slots": [{"type": "single", "window_ist": "12:00-13:00", "theme": "electronics", "why": "x"}],
                 "emphasis": "push electronics", "watch": "forwards", "cited_numbers": [2100]},
        "report_ids": [1],
        "factcheck": {"status": "passed", "unverified": []},
    }
    with session_scope() as s:
        plan = persist_ai_plan(s, result)
        assert plan is not None
    with session_scope() as s:
        p = s.scalars(select(CampaignPlan)).one()
        assert p.is_ai_generated is True
        assert p.factcheck_status == "passed"
        assert p.blueprint["post_slots"][0]["theme"] == "electronics"
        assert p.ai_digest.startswith("Views up")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ai_execution.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement execution/persistence**

```python
# be/src/services/generation/ai_execution.py
"""Glue: AI plan -> CampaignPlan row -> deterministic scheduling of real deals.
The AI decides strategy (slots); the deterministic planner fills them from real
inventory. Numbers are fact-checked before the plan is trusted."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from src.db.models_campaign import CampaignPlan, PlanType


def _parse_date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except (ValueError, TypeError):
        return None


def persist_ai_plan(s: Session, result: dict) -> CampaignPlan | None:
    if not result.get("available") or not result.get("plan"):
        return None
    plan = result["plan"]
    fc = result.get("factcheck", {"status": "skipped"})
    row = CampaignPlan(
        plan_type=PlanType.DAILY,
        title=f"AI day plan {plan.get('date') or ''}".strip(),
        target_date=_parse_date(plan.get("date")),
        blueprint=plan,
        expected_outcome={"emphasis": plan.get("emphasis"), "watch": plan.get("watch")},
        confidence=0.6 if fc.get("status") == "passed" else 0.3,
        generated_at=datetime.now(timezone.utc),
        is_ai_generated=True,
        ai_digest=result.get("digest", ""),
        cited_numbers=plan.get("cited_numbers", []),
        factcheck_status=fc.get("status", "skipped"),
        report_ids=result.get("report_ids", []),
    )
    s.add(row)
    s.flush()
    return row


def run_ai_daily(s: Session) -> dict:
    from src.ai.planner import generate_day_plan
    from src.ai.factcheck import check_cited_numbers
    from src.ai.context import daily_reports

    result = generate_day_plan(s)
    if not result.get("available"):
        return {"ok": False, "reason": result.get("reason", "ai unavailable")}
    reports = daily_reports(s, days=8)
    fc = check_cited_numbers(result["plan"].get("cited_numbers", []), reports)
    result["factcheck"] = fc
    plan_row = persist_ai_plan(s, result)

    scheduled = None
    if fc["status"] == "passed":
        try:
            from src.services.generation.daily_planner import build_and_schedule_day
            scheduled = build_and_schedule_day(s)
        except Exception as e:
            scheduled = {"ok": False, "reason": str(e)}
    return {
        "ok": True,
        "plan_id": plan_row.id if plan_row else None,
        "factcheck": fc,
        "scheduled": scheduled,
    }
```
> **Note on slot execution:** `build_and_schedule_day` currently derives its own `(hour, category)` slots. Full wiring of the AI slots *into* it is a follow-up; for this task, the AI plan is persisted and the deterministic scheduler runs, so drafts are still produced from real inventory. Passing AI `post_slots` as constraints into `build_and_schedule_day` is a documented enhancement (add a `slots=` kwarg later) — do not fabricate it here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ai_execution.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add be/src/services/generation/ai_execution.py be/tests/test_ai_execution.py
git commit -m "feat(generation): persist AI plan + fact-check gate before deterministic scheduling"
```

---

## Task 12: Deterministic plan adherence

**Files:**
- Create: `be/src/services/analytics/reconciliation.py`
- Test: `be/tests/test_reconciliation_adherence.py` (new)

**Interfaces:**
- Consumes: `CampaignPlan`, `GeneratedPost`/`ScheduledPost` (whichever records published posts + timestamps).
- Produces: `compute_adherence(plan_slots: list[dict], published: list[dict]) -> dict` → `{"planned": int, "published": int, "matched": int, "missed_windows": [str], "by_type": {...}}`. Pure function over plain dicts (no DB) so it is unit-testable.

- [ ] **Step 1: Write the failing test**

```python
# be/tests/test_reconciliation_adherence.py
from src.services.analytics.reconciliation import compute_adherence


def test_adherence_counts_and_missed_windows():
    plan_slots = [
        {"type": "single", "window_ist": "12:00-13:00", "theme": "electronics"},
        {"type": "collection", "window_ist": "19:00-20:00", "theme": "fashion"},
        {"type": "single", "window_ist": "21:00-22:00", "theme": "home"},
    ]
    published = [
        {"type": "single", "hour_ist": 12},
        {"type": "collection", "hour_ist": 19},
    ]
    res = compute_adherence(plan_slots, published)
    assert res["planned"] == 3
    assert res["published"] == 2
    assert res["matched"] == 2
    assert "21:00-22:00" in res["missed_windows"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reconciliation_adherence.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement adherence**

```python
# be/src/services/analytics/reconciliation.py
"""Closed-loop feedback (rescue plan §3.5).
adherence  = deterministic: planned slots vs actually-published posts (FACT).
attribution = correlational: expected_outcome vs actual report (NOT causal)."""
from __future__ import annotations


def _hour_of(window_ist: str) -> int | None:
    try:
        return int(window_ist.split(":")[0])
    except (ValueError, AttributeError, IndexError):
        return None


def compute_adherence(plan_slots: list[dict], published: list[dict]) -> dict:
    planned = len(plan_slots or [])
    pub = list(published or [])
    pub_hours = [p.get("hour_ist") for p in pub]
    matched = 0
    missed_windows: list[str] = []
    remaining = list(pub_hours)
    for slot in plan_slots or []:
        h = _hour_of(slot.get("window_ist", ""))
        # a slot is matched if a post published within +/-1h of its window start
        hit = next((ph for ph in remaining if ph is not None and h is not None and abs(ph - h) <= 1), None)
        if hit is not None:
            matched += 1
            remaining.remove(hit)
        else:
            missed_windows.append(slot.get("window_ist", "?"))

    def _bytype(items, key):
        out: dict[str, int] = {}
        for it in items:
            t = it.get("type", "?")
            out[t] = out.get(t, 0) + 1
        return out

    return {
        "planned": planned,
        "published": len(pub),
        "matched": matched,
        "missed_windows": missed_windows,
        "by_type": {"planned": _bytype(plan_slots or [], "type"), "published": _bytype(pub, "type")},
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reconciliation_adherence.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add be/src/services/analytics/reconciliation.py be/tests/test_reconciliation_adherence.py
git commit -m "feat(analytics): deterministic plan adherence (closed-loop step 1)"
```

---

## Task 13: Expected-vs-actual attribution + reconciliation assembly

**Files:**
- Modify: `be/src/services/analytics/reconciliation.py`
- Test: `be/tests/test_reconciliation_attribution.py` (new)

**Interfaces:**
- Consumes: `DailyChannelReport` (T4), `CampaignPlan` (T7), `compute_adherence` (T12).
- Produces:
  - `compute_attribution(expected_outcome: dict, report: dict) -> dict` — pure diff of predictions vs actuals, each item carrying a `correlational: true` flag.
  - `build_reconciliation(s: Session, plan_date: date) -> dict | None` — loads yesterday's AI `CampaignPlan` + that date's owned `DailyChannelReport` + published posts, returns `{"adherence": {...}, "attribution": {...}, "caveat": "correlational, not causal"}` and writes it onto the plan's `reconciliation` column.

- [ ] **Step 1: Write the failing test**

```python
# be/tests/test_reconciliation_attribution.py
from src.services.analytics.reconciliation import compute_attribution


def test_attribution_diffs_predictions():
    expected = {"electronics_views_pct": 15}
    report = {"electronics_views_pct": 3}
    res = compute_attribution(expected, report)
    item = res["items"][0]
    assert item["metric"] == "electronics_views_pct"
    assert item["expected"] == 15
    assert item["actual"] == 3
    assert res["correlational"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reconciliation_attribution.py -v`
Expected: FAIL — `compute_attribution` not defined.

- [ ] **Step 3: Implement attribution + assembly**

Append to `be/src/services/analytics/reconciliation.py`:
```python
def compute_attribution(expected_outcome: dict, report: dict) -> dict:
    """Diff each expected metric against the actual report value where a matching
    key exists. Correlational only — never asserts the plan caused the outcome."""
    items = []
    for key, exp in (expected_outcome or {}).items():
        if not isinstance(exp, (int, float)) or isinstance(exp, bool):
            continue
        act = report.get(key)
        items.append({
            "metric": key,
            "expected": exp,
            "actual": act if isinstance(act, (int, float)) else None,
            "gap": (act - exp) if isinstance(act, (int, float)) else None,
        })
    return {"items": items, "correlational": True,
            "caveat": "Correlation only; engagement is multi-causal — the plan did not necessarily cause these outcomes."}


def build_reconciliation(s, plan_date):
    """Load yesterday's AI plan + that day's owned report + published posts,
    compute adherence + attribution, store onto the plan.reconciliation column."""
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import select
    from src.db.models_campaign import CampaignPlan, PlanType
    from src.db.models_report import DailyChannelReport, ReportSourceType
    from src.services.analytics.periods import IST

    plan = s.scalars(
        select(CampaignPlan)
        .where(CampaignPlan.plan_type == PlanType.DAILY,
               CampaignPlan.target_date == plan_date,
               CampaignPlan.is_ai_generated == True)  # noqa: E712
        .order_by(CampaignPlan.generated_at.desc())
    ).first()
    if plan is None:
        return None
    report = s.scalars(
        select(DailyChannelReport).where(
            DailyChannelReport.report_date == plan_date,
            DailyChannelReport.source_type == ReportSourceType.OWNED,
        )
    ).first()
    report_d = {}
    if report is not None:
        report_d = {c: getattr(report, c) for c in report.__table__.columns.keys()}

    # published posts for the date (best-effort; fields verified against GeneratedPost/ScheduledPost)
    published: list[dict] = []
    try:
        from src.db.models_generation import GeneratedPost
        start = datetime(plan_date.year, plan_date.month, plan_date.day, tzinfo=IST).astimezone(timezone.utc)
        end = start + timedelta(days=1)
        rows = s.scalars(
            select(GeneratedPost).where(
                GeneratedPost.status == "published",
                GeneratedPost.created_at >= start, GeneratedPost.created_at < end,
            )
        )
        for gp in rows:
            when = getattr(gp, "published_at", None) or gp.created_at
            published.append({"type": getattr(gp, "post_type", "?"),
                              "hour_ist": when.astimezone(IST).hour if when else None})
    except Exception:
        pass

    slots = (plan.blueprint or {}).get("post_slots", [])
    recon = {
        "adherence": compute_adherence(slots, published),
        "attribution": compute_attribution(plan.expected_outcome or {}, report_d),
        "caveat": "Adherence is fact; attribution is correlational, not causal.",
    }
    plan.adherence = recon["adherence"]
    plan.reconciliation = recon
    s.flush()
    return recon
```
> Verify `GeneratedPost` has `status`, `post_type`, `created_at` (confirmed) and whether a `published_at` exists; the `getattr` fallback handles its absence. Adjust the published-status string if the codebase uses an enum value other than `"published"` (check `PostStatus`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reconciliation_attribution.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add be/src/services/analytics/reconciliation.py be/tests/test_reconciliation_attribution.py
git commit -m "feat(analytics): expected-vs-actual attribution + reconciliation assembly (closed-loop step 2)"
```

---

## Task 16: Feed reconciliation into planning + expose digest service

**Files:**
- Modify: `be/src/ai/planner.py` (prepend reconciliation to the prompt when present)
- Modify: `be/src/controllers/service.py` (add `digest()` service function)
- Modify: `be/src/routers/data.py` (add `GET /api/digest`)
- Test: `be/tests/test_digest_service.py` (new)

**Interfaces:**
- Consumes: `run_ai_daily` (T11) or persisted latest AI `CampaignPlan`; `build_reconciliation` (T13).
- Produces:
  - `service.digest() -> dict` — `{available, digest, plan, factcheck_status, reconciliation, generated_at}` from the latest AI `CampaignPlan`.
  - `GET /api/digest` returning `ok(service.digest())`.
  - `planner.generate_day_plan` prepends the prior day's `reconciliation` (if any) to the prompt.

- [ ] **Step 1: Write the failing test**

```python
# be/tests/test_digest_service.py
from __future__ import annotations
import os, tempfile
from datetime import date, datetime, timezone
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
    from src.db.models_campaign import CampaignPlan, PlanType
    init_db()
    with session_scope() as s:
        s.add(CampaignPlan(
            plan_type=PlanType.DAILY, title="AI day plan", target_date=date(2026, 7, 8),
            blueprint={"post_slots": [], "emphasis": "push electronics"},
            confidence=0.6, generated_at=datetime.now(timezone.utc),
            is_ai_generated=True, ai_digest="Yesterday views up 12%.",
            factcheck_status="passed"))
    yield


def test_digest_service_returns_latest_ai_plan():
    from src.controllers.service import digest
    d = digest()
    assert d["available"] is True
    assert d["digest"] == "Yesterday views up 12%."
    assert d["factcheck_status"] == "passed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_digest_service.py -v`
Expected: FAIL — `digest` not defined in service.

- [ ] **Step 3: Implement service + route + prompt feed**

In `be/src/controllers/service.py` add:
```python
def digest() -> dict:
    from sqlalchemy import select
    from src.db.models_campaign import CampaignPlan, PlanType
    from src.db.session import session_scope
    with session_scope() as s:
        p = s.scalars(
            select(CampaignPlan)
            .where(CampaignPlan.plan_type == PlanType.DAILY, CampaignPlan.is_ai_generated == True)  # noqa: E712
            .order_by(CampaignPlan.generated_at.desc())
        ).first()
        if p is None:
            return {"available": False, "digest": "", "plan": None,
                    "factcheck_status": None, "reconciliation": None, "generated_at": None}
        return {
            "available": True,
            "digest": p.ai_digest or "",
            "plan": p.blueprint,
            "factcheck_status": p.factcheck_status,
            "reconciliation": p.reconciliation,
            "generated_at": p.generated_at.isoformat() if p.generated_at else None,
        }
```
In `be/src/routers/data.py` add (alongside `/plans`):
```python
@router.get("/digest")
def digest():
    return ok(service.digest())
```
In `be/src/ai/planner.py`, in `generate_day_plan`, before building `user`, load the latest reconciliation and prepend it:
```python
    recon_note = ""
    try:
        from sqlalchemy import select
        from src.db.models_campaign import CampaignPlan, PlanType
        prev = s.scalars(
            select(CampaignPlan)
            .where(CampaignPlan.plan_type == PlanType.DAILY, CampaignPlan.is_ai_generated == True)  # noqa: E712
            .order_by(CampaignPlan.generated_at.desc())
        ).first()
        if prev is not None and prev.reconciliation:
            recon_note = ("\n\nYESTERDAY'S RECONCILIATION (adherence is fact; attribution is "
                          "correlational, not causal):\n" + to_json(prev.reconciliation))
    except Exception:
        recon_note = ""
    user = f"{_PLAN_INSTRUCTIONS}\n\nDATA:\n{to_json(ctx)}{recon_note}"
```
(Replace the existing `user = ...` line.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_digest_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add be/src/controllers/service.py be/src/routers/data.py be/src/ai/planner.py be/tests/test_digest_service.py
git commit -m "feat(api): /api/digest + feed reconciliation into next-day planning prompt"
```

---

## Task 17: (folded into Task 16 — `/api/digest` route)

Covered by Task 16. No separate work.

---

## Task 18: AI badge component (frontend)

**Files:**
- Create: `next/components/AiBadge.tsx`
- Test: manual (frontend has no unit-test harness per exploration; verify via typecheck/build)

**Interfaces:**
- Produces: `<AiBadge />` — a small pill (icon + "AI") with a distinct token, importable by any page to mark AI-authored blocks.

- [ ] **Step 1: Create the component**

```tsx
// next/components/AiBadge.tsx
import { Sparkles } from "lucide-react";

export function AiBadge({ label = "AI" }: { label?: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border border-violet-400/40 bg-violet-500/10 px-2 py-0.5 text-[11px] font-medium text-violet-500 dark:text-violet-300"
      title="Written by AI — grounded in your report data and fact-checked"
    >
      <Sparkles className="h-3 w-3" />
      {label}
    </span>
  );
}
```
(Confirm `lucide-react` is a dependency — it is used across the existing components; if the icon name differs, use any existing icon import pattern.)

- [ ] **Step 2: Typecheck**

Run: `cd next && npx tsc --noEmit`
Expected: no new errors from `AiBadge.tsx`.

- [ ] **Step 3: Commit**

```bash
git add next/components/AiBadge.tsx
git commit -m "feat(ui): AiBadge component to mark AI-authored blocks"
```

---

## Task 19: Daily Digest page + query hook + nav

**Files:**
- Create: `next/app/(dashboard)/digest/page.tsx`
- Modify: `next/queries/queries.ts` (add `useDigest`)
- Modify: `next/queries/keys.ts` (add `digest` key)
- Modify: `next/constants/nav.ts` (add Digest nav item)

**Interfaces:**
- Consumes: `GET /api/digest` (Task 16), `api` wrapper, `AiBadge` (Task 18).
- Produces: `useDigest()` hook + a Digest page showing the AI digest (badged), today's plan slots, fact-check status, and yesterday's reconciliation.

- [ ] **Step 1: Add query key**

In `next/queries/keys.ts`, add to the keys object:
```ts
  digest: ["digest"] as const,
```

- [ ] **Step 2: Add the hook**

In `next/queries/queries.ts` (mirror the `usePlans` pattern):
```ts
export function useDigest() {
  return useQuery({
    queryKey: keys.digest,
    queryFn: () => api.get<DigestResponse>("/digest"),
  });
}
```
Add a `DigestResponse` type near the other response types (or inline it):
```ts
export type DigestSlot = { type: string; window_ist: string; theme: string; why?: string };
export type DigestResponse = {
  available: boolean;
  digest: string;
  plan: { post_slots?: DigestSlot[]; emphasis?: string; watch?: string } | null;
  factcheck_status: string | null;
  reconciliation: { adherence?: Record<string, unknown>; attribution?: Record<string, unknown>; caveat?: string } | null;
  generated_at: string | null;
};
```

- [ ] **Step 3: Add nav item**

In `next/constants/nav.ts`, add to the `""` (Overview) or `Understand` group — place Digest first under Understand:
```ts
  { to: "/digest", label: "Daily Digest", icon: Sparkles, group: "Understand" },
```
(Import `Sparkles` from `lucide-react` alongside the other icon imports; match the existing `NavItem` shape.)

- [ ] **Step 4: Create the page**

```tsx
// next/app/(dashboard)/digest/page.tsx
"use client";

import { useDigest } from "@/queries/queries";
import { AiBadge } from "@/components/AiBadge";

export default function DigestPage() {
  const { data, isLoading } = useDigest();

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Loading digest…</div>;
  if (!data?.available)
    return (
      <div className="p-6 text-sm text-muted-foreground">
        No AI digest yet — it appears after the first daily report + planning run.
      </div>
    );

  const plan = data.plan;
  const recon = data.reconciliation;

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Daily Digest</h1>
        <AiBadge />
        {data.factcheck_status && (
          <span className="text-xs text-muted-foreground">fact-check: {data.factcheck_status}</span>
        )}
      </header>

      <section className="rounded-lg border p-4">
        <div className="mb-2 flex items-center gap-2">
          <h2 className="text-sm font-medium">How yesterday went → today's focus</h2>
          <AiBadge />
        </div>
        <p className="text-sm leading-relaxed">{data.digest}</p>
      </section>

      {plan?.post_slots?.length ? (
        <section className="rounded-lg border p-4">
          <h2 className="mb-3 text-sm font-medium">Today's plan</h2>
          <ul className="flex flex-col gap-2">
            {plan.post_slots.map((s, i) => (
              <li key={i} className="flex items-center justify-between rounded-md bg-muted/40 px-3 py-2 text-sm">
                <span className="font-medium">{s.window_ist}</span>
                <span>{s.type}</span>
                <span className="text-muted-foreground">{s.theme}</span>
              </li>
            ))}
          </ul>
          {plan.emphasis && <p className="mt-3 text-sm"><b>Emphasis:</b> {plan.emphasis}</p>}
          {plan.watch && <p className="text-sm"><b>Watch:</b> {plan.watch}</p>}
        </section>
      ) : null}

      {recon && (
        <section className="rounded-lg border p-4">
          <h2 className="mb-2 text-sm font-medium">Yesterday: planned vs actual</h2>
          <pre className="overflow-x-auto rounded bg-muted/40 p-3 text-xs">{JSON.stringify(recon, null, 2)}</pre>
          {recon.caveat && <p className="mt-2 text-xs text-muted-foreground">{recon.caveat}</p>}
        </section>
      )}
    </div>
  );
}
```
(Match existing Card/utility class conventions if the project uses shadcn `Card`; the classes above assume Tailwind + the existing `muted`/`border` tokens visible in the current pages. Adjust to the real component kit.)

- [ ] **Step 5: Typecheck + build**

Run: `cd next && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
git add next/app/(dashboard)/digest/page.tsx next/queries/queries.ts next/queries/keys.ts next/constants/nav.ts
git commit -m "feat(ui): Daily Digest page + useDigest hook + nav entry"
```

---

## Task 20: Demote emoji/style/strategy dashboard surfaces

**Files:**
- Modify: `next/constants/nav.ts` (remove/demote standalone emoji-style entries if present)
- Modify: `next/app/(dashboard)/growth/page.tsx` (demote "strategy" headline; keep recommendations as supporting evidence)

**Interfaces:** none — presentation only.

- [ ] **Step 1: Audit what's actually surfaced**

Grep the frontend for emoji/style analytics surfaces and the strategy headline:
Run: `cd next && grep -rn "emoji\|Style Profile\|Strategy Blueprint\|blueprint" app components --include=*.tsx`
Identify any dedicated emoji/style section and the growth-page "strategy" headline. Only demote what exists — do not invent removals.

- [ ] **Step 2: Demote in the growth page**

In `next/app/(dashboard)/growth/page.tsx`, change the primary "Strategy" framing so AI planning (the Digest page) is the headline strategy surface; keep `GrowthRecommendation` content as a secondary "supporting evidence" section (retitle the section header, do not delete the data rendering). Remove any standalone "emoji analytics" block if one is rendered.

- [ ] **Step 3: Typecheck**

Run: `cd next && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add next/app/(dashboard)/growth/page.tsx next/constants/nav.ts
git commit -m "refactor(ui): demote emoji/style/strategy surfaces; AI digest is the headline strategy"
```

---

## Self-review notes (spec coverage)

- §2.1 DailyChannelReport → **T4**. §2.4 aggregator → **T5**. §2.5 CampaignPlan cols → **T7**; Competitor cols → **T14**; migrate registration → **T7/T14**.
- §3.1–3.4 AI analyst/planner + reuse plumbing → **T8, T9**. §3.3 fact-checker → **T10**. Execution → **T11**.
- §3.5 closed loop → **T12 (adherence), T13 (attribution + assembly), T16 (feed into prompt)**.
- §4.1 Telethon bug → **T1**. §4.2 scheduler unify → **T2**. §4.3 discovery verifier → **T15**. §4.4 pipeline chaining/ordering → **T3 (decouple)**, competitor report rows → **T5/T16**.
- §5 UI honesty → **T18 (badge), T19 (digest page + route via T16)**. §6 demotions → **T20**.
- Nightly persistence wiring → **T6**.

**Deferred / explicitly out of scope (documented, not silent):** competitor velocity snapshots (§2.2 nice-to-have); passing AI `post_slots` as hard constraints into `build_and_schedule_day` (T11 note — deterministic scheduler still runs); `ANTHROPIC_API_KEY` cleanup (§9 low priority). These are called out so nothing reads as "done" when it isn't.
