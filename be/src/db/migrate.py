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
    ],
    "users": [
        ("password_hash", "VARCHAR(255)"),
        ("last_login_at", "DATETIME"),
    ],
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
