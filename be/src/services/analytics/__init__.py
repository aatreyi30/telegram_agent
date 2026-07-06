"""Analytics — honest, views-based statistics over the data we actually have.

We are a *member* (not admin) of the channel, so Telegram's admin-only Statistics
(subscriber growth, shares-by-source, reach) are unavailable. Everything here is
computed from the real per-post view counts, and every figure is labelled with the
period it covers and its sample size (see ``periods``) so nothing reads as vague.
"""

from src.services.analytics.periods import (
    IST,
    competitor_window,
    owned_window,
    period_label,
    sample_note,
)

__all__ = ["IST", "owned_window", "competitor_window", "period_label", "sample_note"]
