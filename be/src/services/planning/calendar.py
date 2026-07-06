"""India deal-calendar (source_truth research: annual events are known; flash
sales are NOT predictable).

Honest dates (RULE 1): national/festival dates that are fixed are marked EXACT;
merchant sale events (GIF, BBD, EORS, GOAT, Prime Day) shift year to year and are
announced close to the event, so they are month-level APPROXIMATE and flagged —
never fabricated as precise. Flash sales are intentionally absent (unpredictable).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models_campaign import DateConfidence, SaleEvent

# key, name, type, merchant, month, day(None=approx month), window_days, confidence, notes
_SEED = [
    ("new_year_sale", "New Year Sale", "shopping", None, 1, 1, 5, DateConfidence.EXACT,
     "Cross-merchant New Year discounts."),
    ("republic_day_sale", "Republic Day Sale", "shopping", None, 1, 26, 4, DateConfidence.EXACT,
     "Major Jan sale window (Amazon/Flipkart Republic Day sales)."),
    ("holi_sale", "Holi Sale", "festival", None, 3, None, 4, DateConfidence.APPROXIMATE,
     "Holi date varies (Feb/Mar); confirm near event."),
    ("prime_day", "Amazon Prime Day", "merchant_sale", "amazon", 7, None, 2, DateConfidence.APPROXIMATE,
     "Amazon Prime Day ~July; exact dates announced ~2 weeks before."),
    ("independence_day_sale", "Independence Day Sale", "shopping", None, 8, 15, 4, DateConfidence.EXACT,
     "Aug 15 Freedom sale window across merchants."),
    ("myntra_eors", "Myntra End of Reason Sale", "merchant_sale", "myntra", 6, None, 4, DateConfidence.APPROXIMATE,
     "EORS runs ~June & ~Dec; confirm dates near event."),
    ("gandhi_jayanti", "Gandhi Jayanti Sale", "shopping", None, 10, 2, 3, DateConfidence.EXACT,
     "Early-Oct sale, often overlaps festival ramp-up."),
    ("amazon_gif", "Amazon Great Indian Festival", "merchant_sale", "amazon", 10, None, 7, DateConfidence.APPROXIMATE,
     "GIF ~October; channels historically 3-5x posting. Exact dates announced near event."),
    ("flipkart_bbd", "Flipkart Big Billion Days", "merchant_sale", "flipkart", 10, None, 7, DateConfidence.APPROXIMATE,
     "BBD ~October; peak shopping event. Exact dates announced near event."),
    ("diwali_sale", "Diwali Sale", "festival", None, 11, None, 7, DateConfidence.APPROXIMATE,
     "Diwali date varies (late Oct / Nov); confirm exact date near event."),
    ("ajio_goat", "AJIO GOAT Sale", "merchant_sale", "ajio", 12, None, 5, DateConfidence.APPROXIMATE,
     "AJIO's flagship sale ~December; confirm near event."),
]


def _next_occurrence(today: date, month: int, day: int | None) -> date:
    """Next occurrence of the (month, day) on/after today. Approximate events
    (day=None) map to the 1st of that month."""
    d = day or 1
    year = today.year
    try:
        cand = date(year, month, d)
    except ValueError:  # e.g. day out of range
        cand = date(year, month, 1)
    if cand < today:
        cand = date(year + 1, month, d)
    return cand


def seed_sale_events(s: Session, today: date) -> int:
    changed = 0
    for key, name, etype, merchant, month, day, window, conf, notes in _SEED:
        nxt = _next_occurrence(today, month, day)
        row = s.scalar(select(SaleEvent).where(SaleEvent.key == key))
        if row is None:
            row = SaleEvent(key=key)
            s.add(row)
            changed += 1
        row.name, row.event_type, row.merchant_key = name, etype, merchant
        row.next_date, row.window_days = nxt, window
        row.date_confidence, row.notes = conf, notes
    return changed


def upcoming_events(s: Session, today: date, within_days: int = 400) -> list[SaleEvent]:
    rows = s.scalars(
        select(SaleEvent).where(SaleEvent.next_date.isnot(None)).order_by(SaleEvent.next_date)
    ).all()
    return [e for e in rows if 0 <= (e.next_date - today).days <= within_days]
