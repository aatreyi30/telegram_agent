"""Integration coverage for the agentic daily/weekly planning wiring:
- daily_brief's headline `recommended_posts`/`cadence_why` now come from the AI's own
  plan, safety-clamped against the deterministic median/30d max.
- weekly_brief persists the AI digest onto the current week's CampaignPlan row and
  exposes per-day follower deltas alongside posts/views."""
from __future__ import annotations
import os, tempfile
from datetime import date, datetime, timedelta, timezone
import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db, session_scope
    from src.db.models import Channel, Post
    from src.db.models_normalization import NormalizedPost, SourceType
    from src.db.models_campaign import CampaignPlan, PlanType
    from src.db.models_growth_snapshot import DailySubscriberStat

    init_db()
    with session_scope() as s:
        ch = Channel(tg_channel_id=1, username="c", title="C")
        s.add(ch)
        s.flush()

        # 60 days of steady 1-post/day owned activity ending 2026-06-30, so every
        # daily_brief target date used below (07-01..07-03) sees the same
        # deterministic median (1) and 30d max (1) regardless of small day shifts.
        base = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
        for i in range(60):
            p = Post(channel_id=ch.id, tg_message_id=i, posted_at=base - timedelta(days=i),
                     collected_at=base, views=50)
            s.add(p)
            s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                 normalized_at=base, primary_merchant_key="amazon"))

        # 7 days of owned posts + a WEEKLY blueprint + subscriber stats for weekly_brief.
        # weekly_brief now resolves "end=2026-07-08" (a Wednesday) to the real IST
        # calendar week containing it: Mon 2026-07-06 -> Sun 2026-07-12.
        wk_base = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
        for i in range(7):
            p = Post(channel_id=ch.id, tg_message_id=1000 + i, posted_at=wk_base - timedelta(days=i),
                     collected_at=wk_base, views=80)
            s.add(p)
            s.flush()
            s.add(NormalizedPost(source_id=p.id, source_type=SourceType.OWNED,
                                 normalized_at=wk_base, primary_merchant_key="amazon"))

        s.add(CampaignPlan(
            plan_type=PlanType.WEEKLY, title="Week of 2026-07-06",
            target_date=date(2026, 7, 6), end_date=date(2026, 7, 12),
            blueprint={"daily_themes": {}}, confidence=0.5,
            generated_at=datetime.now(timezone.utc), is_ai_generated=False))

        s.add(DailySubscriberStat(
            channel_id=ch.id, stat_date=date(2026, 7, 6),
            subs_start=1000, subs_end=1010, subs_joined=10, subs_left=2, subs_net=8))
        s.add(DailySubscriberStat(
            channel_id=ch.id, stat_date=date(2026, 7, 9),
            subs_start=1010, subs_end=1010, subs_joined=5, subs_left=5, subs_net=0))
        s.flush()
    yield


def _plan(recommended_posts, cadence_why):
    return {
        "available": True,
        "digest": "AI daily digest.",
        "plan": {"recommended_posts": recommended_posts, "cadence_why": cadence_why,
                 "post_slots": [], "emphasis": None, "watch": None, "cited_numbers": []},
        "facts": [],
    }


def test_daily_brief_uses_ai_number_when_in_range(monkeypatch):
    from src.controllers import service

    monkeypatch.setattr(
        "src.ai.planner.generate_day_plan",
        lambda s, day=None, inputs=None: _plan(2, "AI says 2 is right"),
    )
    r = service.daily_brief(date="2026-07-01")
    assert r["today"]["recommended_posts"] == 2
    assert r["today"]["plan_clamped"] is False
    # cadence_why is the deterministic line, now keyed to the DISPLAYED count (2) so the
    # headline and the sentence can never name different numbers. The seeded history is a
    # steady 1/day (range 1–1), so the AI's 2 sits OUTSIDE that range — the honest line is
    # "planning ~2 today", NOT a false "~2 matches that pace" (that claim is reserved for
    # counts inside the observed range). Never the AI's own drifting prose.
    cw = r["today"]["cadence_why"]
    assert "AI says" not in cw
    assert "planning ~2 today" in cw and "matches that pace" not in cw


def test_daily_brief_clamps_out_of_range_ai_number(monkeypatch):
    from src.controllers import service

    monkeypatch.setattr(
        "src.ai.planner.generate_day_plan",
        lambda s, day=None, inputs=None: _plan(10, "AI says 10, way too many"),
    )
    r = service.daily_brief(date="2026-07-02")
    assert r["today"]["recommended_posts"] == 3  # clipped to 3 * recent_max_30d (1)
    assert r["today"]["plan_clamped"] is True
    assert "active days ran" in r["today"]["cadence_why"]  # deterministic fallback text


def test_daily_brief_falls_back_to_deterministic_when_ai_unavailable(monkeypatch):
    from src.controllers import service

    monkeypatch.setattr(
        "src.ai.planner.generate_day_plan",
        lambda s, day=None, inputs=None: {"available": False},
    )
    r = service.daily_brief(date="2026-07-03")
    assert r["ai_available"] is False
    assert r["today"]["recommended_posts"] == 1  # deterministic median
    assert r["today"]["plan_clamped"] is False
    assert "active days ran" in r["today"]["cadence_why"]


def test_weekly_brief_adds_follower_deltas_and_persists_digest(monkeypatch):
    from sqlalchemy import select
    from src.controllers import service
    from src.db.session import session_scope
    from src.db.models_campaign import CampaignPlan, PlanType, CAMPAIGN_VERSION

    monkeypatch.setattr(
        "src.ai.planner.generate_week_plan",
        lambda s, week_start=None, directive=None, end_day=None, **_kw: {"available": True, "digest": "Weekly digest text."},
    )

    r = service.weekly_brief(end="2026-07-08")
    assert r["ai_available"] is True
    assert r["digest"] == "Weekly digest text."

    # TRAILING 7-day window ending at the anchor (2026-07-08), not a Mon->Sun week.
    assert r["week_start"] == "2026-07-02"
    assert r["week_end"] == "2026-07-08"

    by_date = {d["date"]: d for d in r["days"]}
    # Each day carries only real per-day POSTS/VIEWS — follower deltas were removed
    # (Telegram has no subscriber history to give a reliable per-day joined/left/net).
    assert set(by_date["2026-07-07"]) == {"date", "weekday", "posts", "views_avg", "views_maturing"}
    assert "joined" not in by_date["2026-07-07"]
    # The window ends AT the anchor — no future days past it.
    assert "2026-07-09" not in by_date and "2026-07-08" in by_date

    from datetime import date as _date
    with session_scope() as s:
        wk = s.scalar(select(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.WEEKLY,
            CampaignPlan.target_date == _date(2026, 7, 2)))  # the trailing window's start
        assert wk.ai_digest == "Weekly digest text."
        assert wk.is_ai_generated is True


def test_weekly_brief_reuses_cached_digest_on_second_call(monkeypatch):
    """Regression test: weekly_brief() must call the AI at most once per window (keyed
    by the trailing window's start). Before this fix it had no create-path for a
    missing WEEKLY CampaignPlan row (unlike daily_brief()'s persist_ai_plan) — every
    call fell through to a fresh, non-deterministic Groq call: open the plan twice, get
    two different digests."""
    from src.controllers import service

    calls = {"n": 0}

    def _fake_generate(s, week_start=None, directive=None, end_day=None, **_kw):
        calls["n"] += 1
        return {"available": True, "digest": f"Digest attempt #{calls['n']}"}

    monkeypatch.setattr("src.ai.planner.generate_week_plan", _fake_generate)

    # A window with no pre-existing CampaignPlan row or seeded data — exercises the
    # create-path that was missing: weekly_brief() previously could only UPDATE an
    # existing row, never INSERT one, so it called the AI fresh on every request.
    first = service.weekly_brief(end="2026-09-02")
    second = service.weekly_brief(end="2026-09-02")

    assert calls["n"] == 1, "AI must only be called once for the same trailing window"
    assert first["digest"] == "Digest attempt #1"
    assert second["digest"] == "Digest attempt #1"  # reused, not "attempt #2"
    # The trailing window ends at the anchor: end=2026-09-02 -> start 2026-08-27.
    assert first["week_start"] == "2026-08-27" and first["week_end"] == "2026-09-02"


def test_daily_brief_floors_recommended_posts_to_the_weekly_event_ramp(monkeypatch):
    """The gap the operator flagged: the weekly page could say '70/day for Independence
    Day Sale' while the Daily tab for a day inside that same week still showed the
    ordinary ~1/day, completely unaware of the event. daily_brief must now read the
    SAME persisted weekly event_ramp (single source of truth, never re-derived) and
    floor recommended_posts up to it — never down, and only for a day the weekly plan's
    own date range actually covers."""
    from datetime import date as _date, datetime as _dt, timezone as _tz
    from src.controllers import service
    from src.db.models_campaign import CampaignPlan, PlanType
    from src.db.session import session_scope

    with session_scope() as s:
        s.add(CampaignPlan(
            plan_type=PlanType.WEEKLY, title="Week of 2026-07-27",
            target_date=_date(2026, 7, 27), end_date=_date(2026, 8, 2),
            blueprint={"event_ramp": {"event": "Test Sale", "days_away": 2,
                                      "merchant_key": None, "multiplier": 3.0,
                                      "baseline_posts_per_day": 1, "ramped_posts_per_day": 30}},
            confidence=0.6, generated_at=_dt.now(_tz.utc), is_ai_generated=True))

    # AI unavailable -> deterministic fallback path, so the floor is the ONLY thing
    # deciding the count (no AI number in play to muddy the assertion). generate_day_plan
    # never raises to its caller (G6: it catches AIUnavailable internally and returns a
    # fallback dict) — mirror that shape directly rather than raising through the fake.
    monkeypatch.setattr(
        "src.ai.planner.generate_day_plan",
        lambda s, day=None, inputs=None, **_kw: {"available": False, "reason": "down",
                                                  "plan": None, "digest": "", "facts": []},
    )

    r = service.daily_brief(date="2026-07-29")   # inside the seeded week's range
    assert r["today"]["recommended_posts"] == 30
    cw = r["today"]["cadence_why"]
    assert "ramped to ~30" in cw and "Test Sale" in cw
    # The historical-fact clause must state the TRUE observed baseline (the fixture's
    # seeded history doesn't reach July 2026, so it's genuinely 0), never the ramped 30
    # — that sentence describes what actually happened, not the event target.
    assert "ran ~0 posts/day" in cw

    # A day OUTSIDE the seeded week's range must NOT be floored — proves the date-range
    # guard actually scopes the ramp, it isn't a global sticky override.
    r2 = service.daily_brief(date="2026-07-05")
    assert r2["today"]["recommended_posts"] != 30
    assert "Test Sale" not in r2["today"]["cadence_why"]


def test_daily_brief_upcoming_event_callout_ignores_context_only_events(monkeypatch):
    """A plain observance/holiday (e.g. "Friendship Day") must never surface the
    "consider ramping" callout — only a sale-flavored event (type in _RAMP) should.
    Regression for a real live bug: seeding the Aug 2026 festival/holiday calendar
    made `upcoming_events(...)[0]` (unfiltered by type) pick the nearest ANY event,
    surfacing "Friendship Day ... consider ramping" in the UI."""
    from datetime import date as _date
    from src.controllers import service
    from src.db.models_campaign import SaleEvent
    from src.db.session import session_scope

    monkeypatch.setattr(
        "src.ai.planner.generate_day_plan",
        lambda s, day=None, inputs=None, **_kw: {"available": False, "reason": "down",
                                                  "plan": None, "digest": "", "facts": []},
    )

    with session_scope() as s:
        s.add(SaleEvent(key="test_observance", name="Friendship Day",
                        event_type="observance", merchant_key=None,
                        next_date=_date(2026, 7, 6), window_days=1,
                        date_confidence="approximate"))
    r = service.daily_brief(date="2026-07-01")
    assert r["upcoming_event"] is None

    with session_scope() as s:
        s.add(SaleEvent(key="test_merchant_sale", name="Flipkart Test Sale",
                        event_type="merchant_sale", merchant_key="flipkart",
                        next_date=_date(2026, 7, 4), window_days=3,
                        date_confidence="approximate"))
    r2 = service.daily_brief(date="2026-07-02")
    assert r2["upcoming_event"] is not None
    assert r2["upcoming_event"]["name"] == "Flipkart Test Sale"


def test_weekly_brief_event_ramp_merchant_bias_survives_ai_merge(monkeypatch):
    """The AI's own weekly plan unconditionally overwrites merchant_priorities from
    ai_plan.get(...) — even when that's None. An active event's merchant bias (and the
    honest cadence-ramp note) must be reapplied AFTER that merge, so it survives an AI
    response that says nothing about merchant priorities at all."""
    from datetime import date as _date
    from src.controllers import service
    from src.db.models_campaign import SaleEvent
    from src.db.session import session_scope

    with session_scope() as s:
        s.add(SaleEvent(key="test_flipkart_sale", name="Flipkart Test Sale",
                        event_type="merchant_sale", merchant_key="flipkart",
                        next_date=_date(2026, 10, 11), window_days=3,
                        date_confidence="approximate"))

    def _fake_generate(s, week_start=None, directive=None, end_day=None, active_event=None, **_kw):
        assert active_event is not None and active_event["merchant_key"] == "flipkart"
        return {"available": True, "digest": "AI digest, no merchant priorities mentioned.",
                "plan": {"merchant_priorities": None, "loot_deal_ratio": None,
                        "direction": "AI direction text.", "daily_themes": None}}
    monkeypatch.setattr("src.ai.planner.generate_week_plan", _fake_generate)

    r = service.weekly_brief(end="2026-10-14")
    assert r["merchant_priorities"], "event's merchant must survive even when the AI gave none"
    assert r["merchant_priorities"][0]["merchant"] == "flipkart"
    assert "Cadence ramped" in r["digest"] and "Flipkart Test Sale" in r["digest"]
    assert r["recommended_posts_per_day"] > (r.get("event_ramp") or {}).get("baseline_posts_per_day", 0)
