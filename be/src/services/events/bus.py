"""In-process publish/subscribe bus with durable persistence.

A subscriber failure must never corrupt collection (spec 08: "Collection
failures must never corrupt existing data"), so subscriber exceptions are
caught and logged, not propagated to the publisher.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from src.db.models import CollectionEvent
from src.db.session import session_scope
from src.services.events.types import Event
from src.logger import get_logger

logger = get_logger(__name__)

Subscriber = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscriber]] = defaultdict(list)
        self._wildcard: list[Subscriber] = []

    def subscribe(self, event_type: str | None, handler: Subscriber) -> None:
        """Subscribe to one event type, or all events when ``event_type`` is None."""
        if event_type is None:
            self._wildcard.append(handler)
        else:
            self._subscribers[event_type].append(handler)

    def publish(self, event: Event, *, persist: bool = True) -> None:
        if persist:
            self._persist(event)
        for handler in self._subscribers.get(event.event_type, []) + self._wildcard:
            try:
                handler(event)
            except Exception:  # noqa: BLE001 - isolate subscriber failures
                logger.exception(
                    "event subscriber failed for %s (entity %s:%s)",
                    event.event_type,
                    event.entity_type,
                    event.entity_id,
                )

    @staticmethod
    def _persist(event: Event) -> None:
        try:
            with session_scope() as s:
                s.add(
                    CollectionEvent(
                        event_type=event.event_type,
                        entity_type=event.entity_type,
                        entity_id=str(event.entity_id),
                        job_id=event.job_id,
                        data=event.data or None,
                        created_at=event.created_at,
                    )
                )
        except Exception:  # noqa: BLE001
            logger.exception("failed to persist event %s", event.event_type)


_BUS: EventBus | None = None


def get_event_bus() -> EventBus:
    global _BUS
    if _BUS is None:
        _BUS = EventBus()
    return _BUS
