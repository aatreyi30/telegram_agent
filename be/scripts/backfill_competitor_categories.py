"""One-time backfill: classify all existing competitors as 'platform' or 'channel'.

Usage:
    cd be
    python -m scripts.backfill_competitor_categories
"""

import sys
sys.path.insert(0, "src")

from src.db.models import Competitor
from src.db.session import session_scope
from src.services.collection.platform_detector import detect
from sqlalchemy import select


def main():
    updated = skipped = 0
    with session_scope() as s:
        competitors = s.scalars(select(Competitor)).all()
        for c in competitors:
            if c.category is not None:
                skipped += 1
                continue
            cat = detect(title=c.title, username=c.username)
            c.category = cat
            updated += 1
            status = "DIRECT (platform)" if cat == "platform" else "indirect"
            print(f"  {c.username:25s} -> {status}")

        if updated:
            s.flush()
            print(f"\nDone. {updated} classified, {skipped} already had a category.")
        else:
            print("No unclassified competitors found.")


if __name__ == "__main__":
    main()
