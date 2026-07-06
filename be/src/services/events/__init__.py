"""Collection event bus (Phase 1).

Collectors emit structured events after successful collection; downstream
intelligence engines (later phases) subscribe rather than polling external
systems (spec 08 "Events" section). Events are both dispatched in-process and
persisted to ``collection_events`` so a restarted subscriber can catch up.
"""

from src.services.events.types import EventType, Event
from src.services.events.bus import EventBus, get_event_bus

__all__ = ["EventType", "Event", "EventBus", "get_event_bus"]
