"""Manual competitor onboarding.

An admin can add a competitor directly (instead of waiting for Telegram-search
auto-discovery in discovery.py) and have it join the EXISTING pipeline —
collection -> link resolution -> normalization -> intelligence — the same way
an auto-discovered competitor does via discover_competitors()'s initial
backfill. No separate pipeline logic lives here, only the wiring.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.db.models import CollectionType, Competitor, SourceAccessStatus
from src.db.session import session_scope
from src.logger import get_logger

logger = get_logger(__name__)

# Matches discovery.discover_competitors()'s backfill call for freshly-added
# competitors (initial_backfill=True bounds the actual window to
# NEW_COMPETITOR_HISTORY_DAYS regardless of max_pages).
ONBOARD_MAX_PAGES = 5


def _normalize_username(username: str) -> str:
    return (username or "").strip().lstrip("@")


def _to_dict(c: Competitor) -> dict:
    return {
        "id": c.id,
        "username": c.username,
        "title": c.title,
        "category": c.category,
        "discovered_via": c.discovered_via,
        "verified_by": c.verified_by,
        "resolution_confidence": c.resolution_confidence,
        "access_status": c.access_status,
    }


def insert_competitor(username: str, category: str) -> dict:
    """Fast, synchronous half of onboarding: race-safe insert of the new
    ``Competitor`` row. On a unique-username collision (duplicate manual add,
    or the handle was already auto-discovered) returns the existing row
    instead of raising — same SAVEPOINT pattern as persist_ai_plan/
    persist_weekly_plan in ai_execution.py."""
    handle = _normalize_username(username)
    if not handle:
        raise ValueError("username is required")

    with session_scope() as s:
        try:
            with s.begin_nested():
                row = Competitor(
                    username=handle,
                    discovered_via="manual",
                    verified_by="manual",
                    resolution_confidence=1.0,
                    access_status=SourceAccessStatus.AVAILABLE,
                    category=category,
                )
                s.add(row)
                s.flush()
        except IntegrityError:
            logger.info(
                "[onboarding] manual add for @%s lost the race (already exists) "
                "— reusing the existing row", handle,
            )
            row = s.scalar(select(Competitor).where(Competitor.username == handle))
        return _to_dict(row)


def run_pipeline(username: str) -> None:
    """Slow half of onboarding: run an already-inserted competitor through the
    same four global engines discovery.py's backfill uses, in order. Each stage
    is independently guarded — a Telegram rate-limit or AI outage in a later
    stage must not abort onboarding, since the periodic schedulers re-run these
    same global engines on their own cadence and will pick up anything missed."""
    from src.services.collection.base import JobRunner
    from src.services.collection.link_resolution import LinkResolutionEngine
    from src.services.collection.telegram_competitor import CompetitorCollector
    from src.services.intelligence.competitor import CompetitorIntelligenceEngine
    from src.services.processing.normalizer import PostNormalizer

    handle = _normalize_username(username)
    runner = JobRunner()

    try:
        runner.run_collector(
            CompetitorCollector(handle, max_pages=ONBOARD_MAX_PAGES, initial_backfill=True),
            collection_type=CollectionType.MANUAL,
            target=f"backfill_{handle}",
        )
    except Exception as e:  # noqa: BLE001
        logger.error("[onboarding] collection failed for @%s: %s", handle, e)

    try:
        runner.run_collector(
            LinkResolutionEngine(),
            collection_type=CollectionType.MANUAL,
            target=f"link_resolution_{handle}",
        )
    except Exception as e:  # noqa: BLE001
        logger.error("[onboarding] link resolution failed for @%s: %s", handle, e)

    try:
        runner.run_collector(
            PostNormalizer(include_owned=False, include_competitor=True),
            collection_type=CollectionType.MANUAL,
            target=f"normalize_{handle}",
        )
    except Exception as e:  # noqa: BLE001
        logger.error("[onboarding] normalization failed for @%s: %s", handle, e)

    try:
        runner.run_collector(
            CompetitorIntelligenceEngine(),
            collection_type=CollectionType.MANUAL,
            target=f"competitor_intel_{handle}",
        )
    except Exception as e:  # noqa: BLE001
        logger.error("[onboarding] intelligence engine failed for @%s: %s", handle, e)


def onboard_competitor(username: str, category: str) -> dict:
    """Convenience wrapper (CLI/tests) doing both halves back-to-back. The HTTP
    route uses insert_competitor()/run_pipeline() split so the response doesn't
    block on the slow half."""
    record = insert_competitor(username, category)
    run_pipeline(record["username"])
    return record
