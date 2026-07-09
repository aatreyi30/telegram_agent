"""Tiny additive migrations for SQLite.

The project creates tables with ``Base.metadata.create_all`` (no Alembic runs in
practice). ``create_all`` never ALTERs an existing table, so columns added to a
model after its table already exists on disk won't appear. This helper performs
idempotent ``ALTER TABLE ... ADD COLUMN`` for those known additive changes.

Only additive (nullable / defaulted) columns — safe on SQLite, no data loss.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.logger import get_logger

logger = get_logger(__name__)

# table -> [(column, SQL type + default clause)]
_ADDITIONS: dict[str, list[tuple[str, str]]] = {
    "channels": [
        ("org_id", "INTEGER"),
        ("kind", "VARCHAR(16) DEFAULT 'owned'"),
        ("status", "VARCHAR(16) DEFAULT 'active'"),
        ("stats_synced_at", "DATETIME"),
    ],
    "generated_posts": [
        ("strategy_rationale", "JSON"),
        ("channel_id", "INTEGER"),
    ],
    "users": [
        ("password_hash", "VARCHAR(255)"),
        ("last_login_at", "DATETIME"),
    ],
    # multi-tenancy: attribute each derived row to a channel (backfilled by backfill_channel_id)
    "campaign_plans": [
        ("channel_id", "INTEGER"),
        ("is_ai_generated", "BOOLEAN DEFAULT 0"),
        ("ai_digest", "TEXT"),
        ("cited_numbers", "JSON"),
        ("factcheck_status", "VARCHAR(16)"),
        ("report_ids", "JSON"),
        ("adherence", "JSON"),
        ("reconciliation", "JSON"),
    ],
    "channel_style_profiles": [("channel_id", "INTEGER")],
    "post_type_performance": [("channel_id", "INTEGER")],
    "learning_records": [("channel_id", "INTEGER")],
    "growth_strategies": [("channel_id", "INTEGER")],
    "growth_recommendations": [("channel_id", "INTEGER")],
    "reasoned_insights": [("channel_id", "INTEGER")],
    "normalized_posts": [("channel_id", "INTEGER")],
    "competitors": [
        ("category", "VARCHAR(16)"),
        ("resolution_confidence", "FLOAT"),
        ("verified_by", "VARCHAR(16)"),
    ],
    # link resolution bookkeeping (async rewrite): distinguish "never attempted"
    # (NULL) from "failed" / "resolved" / "no_match", and cap retries.
    "extracted_links": [
        ("resolution_status", "VARCHAR(16)"),
        ("resolution_error", "TEXT"),
        ("resolution_attempts", "INTEGER DEFAULT 0"),
    ],
}


# tables whose ORM model was removed from the codebase; drop them from disk since
# create_all() only ever creates tables, it never drops orphaned ones.
_REMOVED_TABLES: tuple[str, ...] = ("channel_stat_snapshots", "competitor_signals")


def _existing_columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}  # r[1] = column name


def add_missing_columns(engine: Engine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        return  # this helper targets the project's SQLite store only
    with engine.begin() as conn:
        existing_tables = {
            r[0] for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        }
        for table, cols in _ADDITIONS.items():
            if table not in existing_tables:
                continue  # create_all will have made it with all columns already
            have = _existing_columns(conn, table)
            for name, decl in cols:
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {decl}"))
                    logger.info("[migrate] added %s.%s", table, name)


def drop_removed_tables(engine: Engine) -> None:
    """Drop tables whose ORM model has been deleted from the codebase. Idempotent:
    ``DROP TABLE IF EXISTS`` is a no-op once the table is gone."""
    if not engine.url.get_backend_name().startswith("sqlite"):
        return  # this helper targets the project's SQLite store only
    with engine.begin() as conn:
        existing_tables = {
            r[0] for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        }
        for table in _REMOVED_TABLES:
            if table in existing_tables:
                conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
                logger.info("[migrate] dropped removed table %s", table)


# derived tables that were computed from the single owned channel before multi-tenancy;
# their NULL channel_id gets attributed to the primary owned channel (the one with posts).
_BACKFILL_TO_PRIMARY = (
    "generated_posts", "campaign_plans", "channel_style_profiles", "post_type_performance",
    "learning_records", "growth_strategies", "growth_recommendations", "reasoned_insights",
)


def backfill_channel_id(engine: Engine) -> None:
    """Attribute pre-multi-tenancy derived rows to a channel. Idempotent: only touches
    rows whose channel_id is still NULL, so it's a no-op once stamped."""
    if not engine.url.get_backend_name().startswith("sqlite"):
        return
    with engine.begin() as conn:
        tables = {r[0] for r in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}

        def has(table: str) -> bool:
            return table in tables and "channel_id" in _existing_columns(conn, table)

        # normalized_posts: an OWNED row inherits its source post's channel_id directly
        if has("normalized_posts") and "posts" in tables:
            conn.execute(text(
                "UPDATE normalized_posts SET channel_id = "
                "(SELECT p.channel_id FROM posts p WHERE p.id = normalized_posts.source_id) "
                "WHERE channel_id IS NULL AND source_type = 'owned'"))

        # everything else was derived from the primary owned channel (most posts)
        row = conn.execute(text(
            "SELECT channel_id FROM posts GROUP BY channel_id "
            "ORDER BY COUNT(*) DESC LIMIT 1")).fetchone()
        primary = row[0] if row else None
        if primary is None:
            return
        for t in _BACKFILL_TO_PRIMARY:
            if has(t):
                n = conn.execute(text(f"UPDATE {t} SET channel_id = :c WHERE channel_id IS NULL"),
                                 {"c": primary}).rowcount
                if n:
                    logger.info("[migrate] backfilled %s.channel_id -> %s (%s rows)", t, primary, n)


def dedupe_and_index_campaign_plans(engine: Engine) -> None:
    """Guard the daily/weekly AI-plan cache against the race where two
    near-simultaneous requests both miss the cache and both persist a plan for the
    same (campaign_version, plan_type, target_date, is_ai_generated) — that used to
    silently create duplicate rows (and burn two AI calls) since the only index was
    the non-unique ``ix_plan_type_date``.

    Before adding the unique index, dedupe any rows that already violate it (keeping
    the most-recently-generated row per group) — SQLite refuses to create a unique
    index over data that isn't unique yet.
    """
    if not engine.url.get_backend_name().startswith("sqlite"):
        return  # this helper targets the project's SQLite store only
    with engine.begin() as conn:
        existing_tables = {
            r[0] for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        }
        if "campaign_plans" not in existing_tables:
            return  # create_all will make it with the index already, nothing to dedupe

        dupes = conn.execute(text(
            "SELECT campaign_version, plan_type, target_date, is_ai_generated, COUNT(*) c "
            "FROM campaign_plans "
            "GROUP BY campaign_version, plan_type, target_date, is_ai_generated "
            "HAVING c > 1"
        )).fetchall()
        deleted = 0
        for cv, ptype, tdate, is_ai, _c in dupes:
            # Keep the newest row (by generated_at) in each dupe group, delete the rest.
            # target_date can be NULL; SQLite's IS/IS NOT handles that correctly, unlike =/!=.
            keep = conn.execute(text(
                "SELECT id FROM campaign_plans "
                "WHERE campaign_version = :cv AND plan_type = :pt "
                "AND target_date IS :td AND is_ai_generated IS :ai "
                "ORDER BY generated_at DESC, id DESC LIMIT 1"
            ), {"cv": cv, "pt": ptype, "td": tdate, "ai": is_ai}).scalar()
            n = conn.execute(text(
                "DELETE FROM campaign_plans "
                "WHERE campaign_version = :cv AND plan_type = :pt "
                "AND target_date IS :td AND is_ai_generated IS :ai AND id != :keep"
            ), {"cv": cv, "pt": ptype, "td": tdate, "ai": is_ai, "keep": keep}).rowcount
            deleted += n
        if deleted:
            logger.info("[migrate] deduped campaign_plans: deleted %s duplicate row(s)", deleted)

        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_plan_version_type_date_ai "
            "ON campaign_plans (campaign_version, plan_type, target_date, is_ai_generated)"
        ))
