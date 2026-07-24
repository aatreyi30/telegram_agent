"""Reset the database to a clean slate, KEEPING only your identity/config rows.

What it keeps (rows preserved):
    organizations   -- your org
    users           -- your login(s) — WITHOUT this you can't sign in
    channels        -- your owned channel name(s)
    competitors     -- the competitor names shown in /settings/competitors

Everything else (all collected posts, metrics, AI outputs, plans, predictions,
outcomes, retros, deal scores, merchant/competitor intel, snapshots, jobs, ...)
is DELETED so you can regenerate it fresh with scripts/collect_data.py.

Safety:
  * Makes a timestamped backup copy of the sqlite file first.
  * DRY-RUN by default — prints what it would delete. Pass --yes to actually do it.
  * Deletes rows only; the schema (tables) is left intact, so the app + a
    subsequent collect run repopulate everything.

Usage (from the be/ directory):
    python scripts/reset_db.py                 # dry-run: show counts, delete nothing
    python scripts/reset_db.py --yes           # perform the reset (after backup)
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import shutil
import sys
from datetime import datetime
from pathlib import Path

# run from anywhere: put the be/ project root (this file's parent's parent) on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# --- populate ORM metadata (import every db model module) -------------------- #
import src.db as _db
from src.db.base import Base
from src.db.session import get_engine
from sqlalchemy import text

for _m in pkgutil.iter_modules(_db.__path__):
    if _m.name.startswith("models"):
        importlib.import_module(f"src.db.{_m.name}")

# Rows in these tables are PRESERVED. Everything else is wiped.
#   - identity/config: organizations, users, channels, competitors
#   - subscriber/follower history: participant_snapshots + daily_subscriber_stats +
#     the per-source breakdowns. This is IRREPLACEABLE — Telegram exposes only the
#     CURRENT count, never history, so once wiped it can never be re-collected and
#     growth resets to zero. Everything else (posts, plans, generated posts, deal
#     data, intel, predictions, outcomes) is recomputable from a fresh collect run.
KEEP = {
    "organizations", "users", "channels", "competitors",
    "participant_snapshots", "daily_subscriber_stats",
    "daily_view_sources", "daily_join_sources",
}


def _sqlite_path(db_url: str) -> Path | None:
    if not db_url.startswith("sqlite"):
        return None
    # sqlite:///./data/tgagent.db  ->  ./data/tgagent.db
    raw = db_url.split("sqlite:///", 1)[-1]
    return Path(raw).resolve()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--yes", action="store_true",
                    help="Actually perform the reset. Without this, dry-run only.")
    args = ap.parse_args()

    engine = get_engine()
    db_file = _sqlite_path(str(engine.url))

    # ordered children-first so FK order never matters (we also disable FKs below)
    ordered = list(reversed(Base.metadata.sorted_tables))
    wipe = [t for t in ordered if t.name not in KEEP]

    print(f"database: {engine.url}")
    print(f"KEEP    : {', '.join(sorted(KEEP))}")
    print("-" * 60)

    with engine.connect() as conn:
        counts = {t.name: conn.execute(text(f"SELECT COUNT(*) FROM {t.name}")).scalar()
                  for t in Base.metadata.sorted_tables}

    kept_summary = {k: counts.get(k, 0) for k in sorted(KEEP)}
    to_delete = {t.name: counts.get(t.name, 0) for t in wipe if counts.get(t.name, 0)}
    total = sum(to_delete.values())

    print("KEEPING (rows preserved):")
    for k, v in kept_summary.items():
        print(f"  {k:<24} {v:>10,}")
    print("\nWIPING (rows to delete):")
    if not to_delete:
        print("  (nothing — already clean)")
    for k, v in sorted(to_delete.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<24} {v:>10,}")
    print("-" * 60)
    print(f"TOTAL rows to delete: {total:,}")

    if not args.yes:
        print("\nDRY-RUN. Nothing deleted. Re-run with --yes to perform the reset.")
        return 0

    if total == 0:
        print("\nNothing to delete. Done.")
        return 0

    # --- backup the sqlite file first ---------------------------------------- #
    if db_file and db_file.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = db_file.with_name(f"{db_file.stem}.backup-{stamp}{db_file.suffix}")
        shutil.copy2(db_file, backup)
        print(f"\nbackup written: {backup}")
    else:
        print("\n[warn] not a local sqlite file — no backup made.")

    # --- wipe ---------------------------------------------------------------- #
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        deleted = 0
        for t in wipe:
            res = conn.execute(t.delete())
            deleted += res.rowcount or 0
        conn.execute(text("PRAGMA foreign_keys=ON"))

    # reclaim space
    with engine.connect() as conn:
        conn.exec_driver_sql("VACUUM")

    print(f"deleted rows across {len(wipe)} tables. Reset complete.")
    print("Kept:", ", ".join(f"{k}={v}" for k, v in kept_summary.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
