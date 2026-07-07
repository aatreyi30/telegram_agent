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
    "campaign_plans": [("channel_id", "INTEGER")],
    "channel_style_profiles": [("channel_id", "INTEGER")],
    "post_type_performance": [("channel_id", "INTEGER")],
    "learning_records": [("channel_id", "INTEGER")],
    "growth_strategies": [("channel_id", "INTEGER")],
    "growth_recommendations": [("channel_id", "INTEGER")],
    "reasoned_insights": [("channel_id", "INTEGER")],
    "normalized_posts": [("channel_id", "INTEGER")],
    "competitors": [("category", "VARCHAR(16)")],
}


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
