"""India deal-calendar (source_truth research: annual events are known; flash
sales are NOT predictable).

Honest dates (RULE 1): national/festival dates that are fixed are marked EXACT;
merchant sale events (GIF, BBD, EORS, GOAT, Prime Day) shift year to year and are
announced close to the event, so they are month-level APPROXIMATE and flagged —
never fabricated as precise. Flash sales are intentionally absent (unpredictable).

Event types, and which ones ramp posting cadence (_RAMP in campaign.py):
  merchant_sale, festival, shopping   -> ramp (real shopping-driving events)
  gazetted_holiday, observance,
  national_observance,
  festival_observance                 -> context only, never ramp — surfaced to
                                          the AI narrative (e.g. "Raksha Bandhan is
                                          2 days away") but don't bump posts_per_day.
`festival_observance` is deliberately a different type string from `festival`:
`festival` is reserved for the handful of festivals that ARE major shopping
events in their own right (Holi, Diwali); other religious/cultural festivals in
the calendar (Nag Panchami, Kajari Teej, ...) don't carry the same automatic
shopping-surge assumption, so they stay context-only unless a real Sale Event
is separately seeded alongside them.

Lunar/movable-date entries (Hindu/Islamic/regional calendars — Shivratri, Teej,
Nag Panchami, Eid, Onam, Raksha Bandhan, Parsi New Year, ...) are seeded with
their real 2026 date but marked APPROXIMATE: the (month, day) recurrence below
is a fixed annual pattern, so these dates will NOT be correct in 2027+ without
a manual re-check and update — flagged here rather than silently drifting wrong.
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

    # --- Aug 2026 calendar batch (manually fed — no live holiday/festival search
    # exists in this app; see calendar.py's own docstring). Dates below are 2026's
    # real dates; lunar/movable ones need re-checking for 2027+ (see module docstring).
    ("friendship_day", "Friendship Day", "observance", None, 8, 2, 1, DateConfidence.APPROXIMATE,
     "Colloquially the first Sunday of August; date shifts yearly."),
    ("myntra_right_to_fashion_sale", "Myntra Right to Fashion Sale", "merchant_sale", "myntra",
     8, 6, 4, DateConfidence.APPROXIMATE, "Tentative start date; confirm near event."),
    ("national_handloom_day", "National Handloom Day", "national_observance", None, 8, 7, 1,
     DateConfidence.EXACT, "Fixed civil date."),
    ("international_beer_day", "International Beer Day", "observance", None, 8, 7, 1,
     DateConfidence.APPROXIMATE, "Observed first Friday of August; date shifts yearly."),
    ("international_cat_day", "International Cat Day", "observance", None, 8, 8, 1,
     DateConfidence.EXACT, "Fixed civil date."),
    ("flipkart_freedom_sale", "Flipkart Freedom Sale", "merchant_sale", "flipkart",
     8, 8, 5, DateConfidence.APPROXIMATE, "Tentative start date; confirm near event."),
    ("quit_india_movement_day", "Quit India Movement Day", "national_observance", None, 8, 9, 1,
     DateConfidence.EXACT, "Fixed civil date."),
    ("croma_independence_day_sale", "Croma Independence Day Sale", "merchant_sale", "croma",
     8, 10, 5, DateConfidence.APPROXIMATE, "Tentative start date; confirm near event."),
    ("sawan_shivratri", "Sawan Shivratri", "festival_observance", None, 8, 11, 1,
     DateConfidence.APPROXIMATE, "Lunar calendar; 2026 date only, re-check for future years."),
    ("ajio_independence_day_sale", "AJIO Independence Day Sale", "merchant_sale", "ajio",
     8, 11, 5, DateConfidence.APPROXIMATE, "Tentative start date; confirm near event."),
    ("international_youth_day", "International Youth Day", "observance", None, 8, 12, 1,
     DateConfidence.EXACT, "Fixed civil date."),
    ("world_elephant_day", "World Elephant Day", "observance", None, 8, 12, 1,
     DateConfidence.EXACT, "Fixed civil date."),
    ("nykaa_independence_day_sale", "Nykaa Independence Day Sale", "merchant_sale", "nykaa",
     8, 12, 4, DateConfidence.APPROXIMATE, "Tentative start date; confirm near event."),
    ("independence_day_holiday", "Independence Day", "gazetted_holiday", None, 8, 15, 2,
     DateConfidence.EXACT, "National holiday — distinct from the cross-merchant independence_day_sale entry."),
    ("hariyali_teej", "Hariyali Teej", "festival_observance", None, 8, 15, 1,
     DateConfidence.APPROXIMATE, "Lunar calendar; 2026 date only, re-check for future years."),
    ("parsi_new_year", "Parsi New Year (Navroz)", "gazetted_holiday", None, 8, 16, 1,
     DateConfidence.APPROXIMATE, "Date varies by calendar variant/region; 2026 date only."),
    ("nag_panchami", "Nag Panchami", "festival_observance", None, 8, 17, 1,
     DateConfidence.APPROXIMATE, "Lunar calendar; 2026 date only, re-check for future years."),
    ("world_photography_day", "World Photography Day", "observance", None, 8, 19, 1,
     DateConfidence.EXACT, "Fixed civil date."),
    ("world_humanitarian_day", "World Humanitarian Day", "observance", None, 8, 19, 1,
     DateConfidence.EXACT, "Fixed civil date."),
    ("sadbhavana_diwas", "Sadbhavana Diwas", "national_observance", None, 8, 20, 1,
     DateConfidence.EXACT, "Fixed civil date."),
    ("world_senior_citizens_day", "World Senior Citizens Day", "observance", None, 8, 21, 1,
     DateConfidence.EXACT, "Fixed civil date."),
    ("madras_day", "Madras Day", "national_observance", None, 8, 22, 1,
     DateConfidence.EXACT, "Fixed civil date."),
    ("national_space_day", "National Space Day", "national_observance", None, 8, 23, 1,
     DateConfidence.EXACT, "Fixed civil date."),
    ("eid_milad_un_nabi", "Eid-e-Milad / Milad-un-Nabi", "gazetted_holiday", None, 8, 26, 1,
     DateConfidence.APPROXIMATE, "Islamic lunar calendar; 2026 date only, re-check for future years."),
    ("onam_thiruvonam", "Onam / Thiruvonam", "gazetted_holiday", None, 8, 26, 2,
     DateConfidence.APPROXIMATE, "Malayalam calendar; 2026 date only, re-check for future years."),
    ("nykaa_rakhi_sale", "Nykaa Rakhi Sale", "merchant_sale", "nykaa",
     8, 26, 4, DateConfidence.APPROXIMATE, "Tentative start date; confirm near event."),
    ("raksha_bandhan", "Raksha Bandhan", "festival_observance", None, 8, 28, 2,
     DateConfidence.APPROXIMATE, "Lunar calendar; 2026 date only, re-check for future years."),
    ("national_sports_day", "National Sports Day", "national_observance", None, 8, 29, 1,
     DateConfidence.EXACT, "Fixed civil date."),
    ("kajari_teej", "Kajari Teej", "festival_observance", None, 8, 31, 1,
     DateConfidence.APPROXIMATE, "Lunar calendar; 2026 date only, re-check for future years."),
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
