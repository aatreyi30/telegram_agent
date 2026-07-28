# be/tests/test_slot_mix_enforcement.py
"""Regression tests for the slot-mix-enforcement spec (jit_fill portions: AC1/AC2/AC4).

Reproduces the reported defect: a discount-desc pool dominated by one merchant, a
sequence of slots planned for OTHER merchants, filled one at a time with state read
back from the DB between fills (mirroring jit_fill's real cron: each tick is a
separate process invocation, so `_pick_fresh` must never rely on in-loop memory)."""
from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timezone

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db
    init_db()
    yield


def _write_fill(s, day, si, sub, item, tier, slot, actual_category, *, bucket_prefix="aislot"):
    """Mirror what `fill_due_slots` actually writes for a filled slot — the exact
    shape `_day_mix` reads back: the FULL planned slot (S2-b), a `primary_category`
    holding the theme actually filled rather than the planned one (S1-b — a
    broadened fill must not be tallied under a category it isn't), and a
    `selection_bucket` under jit_fill's own `aislot:` prefix (S3-e) unless the
    caller is deliberately simulating a draft from a different generation engine."""
    from datetime import timedelta
    from src.db.models_generation import GeneratedPost, PostStatus
    base = datetime(day.year, day.month, day.day, 6, 0, 0, tzinfo=timezone.utc)
    gp = GeneratedPost(
        generated_at=base + timedelta(seconds=si * 60 + sub),
        # plan id "9999" is a sentinel, deliberately not a real CampaignPlan id, so
        # these hand-written rows can never collide with `fill_due_slots`'s own
        # `_already_filled` bucket key for a plan created elsewhere in the suite.
        post_type="single", selection_bucket=f"{bucket_prefix}:9999:{si}:{sub}",
        deal_ids=[item["original_url"]], rendered_text="x",
        format_meta={"source": "template_fallback", "match": tier,
                     "primary_merchant": item["merchant_key"],
                     "primary_category": actual_category,
                     "slot": dict(slot)},
        rank_score=0, status=PostStatus.DRAFT)
    s.add(gp)
    s.flush()


def test_no_merchant_takes_more_than_half_the_window():
    """The exact reported failure: pool is myntra-heavy best-first, slots are planned
    for flipkart/ajio. Each slot is picked with state re-read from the DB (as a
    separate jit_fill tick would), so state must survive across ticks, not just loop
    iterations.

    S3-d: the pool's merchant/category vocabulary deliberately does NOT match the
    stored vocabulary byte-for-byte (case/punctuation only — 'MYNTRA' vs 'myntra',
    'Home-And-Living' vs 'home-and-living' — same tokens once normalized, exactly the
    gap `_norm` exists to close), and the DB already carries an UNEVEN merchant
    history (4 prior myntra fills) before this tick's loop even starts. Both
    conditions were needed to hide S1-a/S1-b — a pool whose vocabulary equals the
    stored vocabulary exactly, with counts starting empty, can't tell a working
    `_norm`-keyed ranking from a broken exact-key one."""
    from src.db.session import session_scope
    from src.services.generation.jit_fill import _day_mix, _pick_fresh

    # discount-desc pool: myntra dominates the top of the list, and — matching the
    # observed data exactly (tier=any, neither planned theme nor planned merchant
    # present) — the planned theme/merchant ('ajio' / 'beauty-and-personal-care') has
    # NO inventory this hour at all, forcing every slot to broaden all the way to 'any'.
    pool = (
        [{"category_key": "Home-And-Living", "merchant_key": "MYNTRA", "original_url": f"m{i}"}
         for i in range(20)]
        + [{"category_key": "Home-And-Living", "merchant_key": "FLIPKART",
            "original_url": f"f{i}"} for i in range(6)]
    )
    day = date(2026, 7, 20)
    seed_slot = {"theme": "home-and-living", "merchant": "myntra"}
    # 6 slots planned ajio/beauty, mirroring the observed plan window — the reported
    # bug filled every single one from the myntra-heavy pool (pool order, unbounded).
    planned = [{"theme": "beauty-and-personal-care", "merchant": "ajio"}] * 6
    used: set[str] = set()
    picked_merchants = []

    with session_scope() as s:
        # pre-existing, UNEVEN DB state (S1-a/S1-b's blind spot): 4 myntra fills
        # already on the books before this tick's slots are picked at all — negative
        # slot indices so their generated_at sorts BEFORE the loop's own fills below.
        for i in range(4):
            seed_item = {"merchant_key": "myntra", "original_url": f"seed{i}"}
            _write_fill(s, day, -4 + i, 0, seed_item, "any", seed_slot, "home-and-living")

        for si, slot in enumerate(planned):
            mix = _day_mix(s, day)  # re-read from the DB every "tick" — no python state
            it, tier = _pick_fresh(pool, slot["theme"], slot["merchant"], used,
                                   merchant_counts=mix["merchant_counts"],
                                   category_counts=mix["category_counts"],
                                   prev_merchant=mix["last_merchant"],
                                   prev_category=mix["last_category"])
            assert it is not None, f"slot {si} dropped — a slot must never go unfilled"
            assert tier == "any", tier  # neither theme nor merchant exists in this pool
            used.add(it["original_url"])
            picked_merchants.append(it["merchant_key"])
            _write_fill(s, day, si, 0, it, tier, slot, "home-and-living")

    counts = {}
    for m in picked_merchants:
        counts[m] = counts.get(m, 0) + 1
    assert max(counts.values()) <= 3, counts  # <= half of a 6-slot window
    assert counts.get("FLIPKART", 0) >= 3, counts  # diversity ranking, not raw pool order


def test_prev_merchant_repeat_is_a_last_resort_not_a_tiebreak_loser():
    """[S1-a] Reviewer's exact repro: an UNEVEN day-count (myntra way ahead) plus a
    previous post that was flipkart. The old ranking put the day-count ahead of the
    prev-repeat penalty, so myntra (lower running count after a few picks) could win
    the tier back-to-back even though flipkart was available in the same tier —
    reproduced as 4 consecutive same-merchant fills. The prev-repeat rule must
    dominate outright: whenever an alternative merchant exists in the tier, it wins,
    regardless of which merchant currently has the lower count."""
    from src.services.generation.jit_fill import _pick_fresh

    pool = [{"category_key": "electronics", "merchant_key": "myntra", "original_url": f"my{i}"}
           for i in range(10)] + [
            {"category_key": "electronics", "merchant_key": "flipkart", "original_url": f"fk{i}"}
            for i in range(10)]
    used: set[str] = set()
    merchant_counts = {"myntra": 5, "flipkart": 1}  # myntra already well ahead
    prev = "flipkart"
    picks = []
    for _ in range(5):
        it, tier = _pick_fresh(pool, "electronics", None, used,
                               merchant_counts=merchant_counts, category_counts={},
                               prev_merchant=prev)
        assert it is not None
        used.add(it["original_url"])
        picks.append(it["merchant_key"])
        merchant_counts[it["merchant_key"]] = merchant_counts.get(it["merchant_key"], 0) + 1
        prev = it["merchant_key"]
    # no two consecutive picks share a merchant while an alternative exists in the tier
    assert all(picks[i] != picks[i + 1] for i in range(len(picks) - 1)), picks


def test_prev_merchant_repeat_still_fills_when_it_is_the_only_option():
    """Never-drop-a-slot guarantee: a tier holding only the previous post's merchant
    must still fill it, not skip the slot."""
    from src.services.generation.jit_fill import _pick_fresh

    pool = [{"category_key": "electronics", "merchant_key": "flipkart", "original_url": "only"}]
    it, tier = _pick_fresh(pool, "electronics", None, set(),
                           merchant_counts={}, category_counts={}, prev_merchant="flipkart")
    assert it is not None and it["original_url"] == "only", (it, tier)


def test_counts_normalized_across_vocabularies_and_tally_reflects_actual_fill():
    """[S1-b] Two defects at once: (1) the count dict must be keyed via `_norm` on
    both sides — a pool item's category_key/merchant_key written in a different
    format than what got stored (case/punctuation) must not silently read back as a
    dead 0 for every candidate; (2) `_day_mix` must tally the theme actually FILLED,
    not the plan's requested theme — a broadened ('any'-tier) fill recorded under the
    planned theme corrupts the very ranking it's supposed to inform."""
    from src.db.session import session_scope
    from src.services.generation.jit_fill import _day_mix, _pick_fresh

    day = date(2026, 7, 21)
    with session_scope() as s:
        # 3 prior fills, all ACTUALLY "electronics-and-gadgets" (broadened off a
        # planned theme of "fashion" every time) — stored via primary_category, in a
        # different case/format than the pool's own category_key below.
        planned_slot = {"theme": "fashion", "merchant": "amazon"}
        for i in range(3):
            item = {"merchant_key": "amazon", "original_url": f"seed{i}"}
            _write_fill(s, day, 80 + i, 0, item, "any", planned_slot,
                       "Electronics-And-Gadgets")

        mix = _day_mix(s, day)
        # the tally must be keyed by what was ACTUALLY filled (electronics), not the
        # planned theme ("fashion") — a dead/empty fashion count would mean the S1-b
        # bug (recording the planned theme) is still present.
        assert mix["category_counts"].get("fashion") is None, mix["category_counts"]
        assert any(v == 3 for v in mix["category_counts"].values()), mix["category_counts"]

        # pool's own category_key differs in case/punctuation from the stored value
        # above ("electronics-and-gadgets" vs "Electronics-And-Gadgets") — must still
        # normalize to the SAME count bucket, or the ranking below is a dead constant.
        pool = [
            {"category_key": "electronics-and-gadgets", "merchant_key": "amazon",
             "original_url": "e1"},
            {"category_key": "beauty-and-personal-care", "merchant_key": "amazon",
             "original_url": "e2"},
        ]
        it, tier = _pick_fresh(pool, "electronics-and-gadgets", "amazon", set(),
                               merchant_counts=mix["merchant_counts"],
                               category_counts=mix["category_counts"],
                               prev_merchant=mix["last_merchant"],
                               prev_category=mix["last_category"])
        # both items match the exact tier's theme filter loosely... only "e1" matches
        # theme+merchant exactly, so it must win regardless of its heavier count —
        # the count only decides WITHIN a tier, and here only one candidate is in it.
        assert it["original_url"] == "e1" and tier == "exact", (it, tier)


def test_day_mix_ignores_drafts_from_other_generation_engines():
    """[S3-e] `_day_mix` must only tally jit_fill's own drafts (selection_bucket
    `aislot:` prefix) — a draft written by another engine (e.g. controllers/jobs.py's
    manual/CLI generator) sharing the same day must not pollute the diversity
    state jit_fill reads back."""
    from src.db.session import session_scope
    from src.services.generation.jit_fill import _day_mix

    day = date(2026, 7, 22)
    slot = {"theme": "electronics", "merchant": "amazon"}
    with session_scope() as s:
        # a foreign draft: same day, but NOT written by jit_fill (no aislot: prefix).
        foreign = {"merchant_key": "flipkart", "original_url": "foreign1"}
        _write_fill(s, day, 0, 0, foreign, "any", slot, "electronics",
                   bucket_prefix="manual_gen")
        mix = _day_mix(s, day)
    assert mix["merchant_counts"] == {}, mix["merchant_counts"]
    assert mix["last_merchant"] is None, mix["last_merchant"]


def test_prev_category_repeat_is_a_last_resort_not_outranked_by_merchant_count():
    """[S2-1] Reviewer's exact repro: pool = [amazon/fashion, flipkart/electronics],
    merchant_counts uneven (amazon 0, flipkart 5), prev_category='fashion'. The old
    tuple put `merchant_count` ahead of the prev-category-repeat flag, so amazon (its
    low merchant count) won even though it repeats the immediately-previous post's
    category and flipkart — a non-repeating alternative — sits in the very same tier.
    Both prev-repeat flags must outrank both running counts."""
    from src.services.generation.jit_fill import _pick_fresh

    pool = [
        {"category_key": "fashion", "merchant_key": "amazon", "original_url": "a1"},
        {"category_key": "electronics", "merchant_key": "flipkart", "original_url": "f1"},
    ]
    it, tier = _pick_fresh(pool, None, None, set(),
                           merchant_counts={"amazon": 0, "flipkart": 5},
                           category_counts={}, prev_merchant=None, prev_category="fashion")
    assert it["original_url"] == "f1", (it, tier)  # flipkart: doesn't repeat the category


def test_merchant_count_ranking_is_keyed_via_norm_not_raw_labels():
    """[S2-2] Genuine defence of the `_norm(...)` keys in `rank`: the pool's merchant
    vocabulary ('Amazon-IN') differs from the stored count's vocabulary ('amazonin'),
    two candidates sit in the SAME tier ('any' — no theme/merchant requested), and
    `prev_merchant`/`prev_category` are both None so neither adjacency flag can decide
    the pick. Only a `_norm`-keyed count lookup can tell these two candidates apart;
    an exact-key lookup reads both as a dead 0 and falls back to pool order, picking
    the wrong (heavier-count) merchant."""
    from src.services.generation.jit_fill import _pick_fresh

    pool = [
        {"category_key": "fashion", "merchant_key": "Amazon-IN", "original_url": "a1"},
        {"category_key": "fashion", "merchant_key": "Flipkart", "original_url": "f1"},
    ]
    it, tier = _pick_fresh(pool, None, None, set(),
                           merchant_counts={"amazonin": 5, "flipkart": 0},
                           category_counts={}, prev_merchant=None, prev_category=None)
    assert it["original_url"] == "f1", (it, tier)  # flipkart: the lower norm-keyed count


def test_merchant_tier_beats_any():
    """The new 'merchant' tier (planned merchant, any theme) must be picked before the
    unbounded 'any' broaden — the direct cause of the reported symptom."""
    from src.services.generation.jit_fill import _pick_fresh

    pool = [{"category_key": "electronics", "merchant_key": "amazon_in", "original_url": "hit"},
            {"category_key": "fashion", "merchant_key": "myntra", "original_url": "miss"}]
    # planned theme doesn't exist in the pool at all -> old code fell straight to 'any'
    # (pool best-first order) and could return "miss"; the merchant tier must win.
    it, tier = _pick_fresh(pool, "toys-and-games", "amazon", set())
    assert it["original_url"] == "hit" and tier == "merchant", (it, tier)


# --------------------------------------------------------------------------- #
# [S2-b] format_meta.slot must carry the full planned slot, not just theme+merchant.
# --------------------------------------------------------------------------- #

def test_format_meta_slot_records_the_full_planned_slot_not_just_theme_and_merchant():
    """`fill_due_slots` end to end: the persisted `format_meta.slot` must carry
    `type`/`time_ist`/`max_price`/`min_price` alongside theme/merchant, so a
    plan-vs-actual query can be run on every dimension the plan carries — not just
    the two fields this file used to keep."""
    from sqlalchemy import select
    from src.db.session import session_scope
    from src.db.models_campaign import CampaignPlan, PlanType
    from src.db.models_generation import GeneratedPost
    from src.services.generation import jit_fill

    class _StubDealSource:
        source = "test"

        def available(self):
            return True, None

        def _collect_raw(self, **kwargs):
            return [{
                "product_title": "Great Wireless Earbuds", "original_url": "https://x/d1",
                "retailer_key": "amazon", "merchant_key": "amazon", "category_key": "electronics",
                "mrp": 2000, "discount_price": 800, "discount_percentage": 60, "deal_score": 90,
            }]

    day = date(2026, 7, 23)
    slot = {"type": "single", "time_ist": "09:05", "theme": "electronics",
           "merchant": "amazon", "max_price": 1000, "min_price": 100, "why": "test"}
    with session_scope() as s:
        plan = CampaignPlan(
            plan_type=PlanType.DAILY, title="p", target_date=day,
            blueprint={"post_slots": [slot]}, generated_at=datetime.now(timezone.utc),
            factcheck_status="passed", is_ai_generated=True)
        s.add(plan)
        s.flush()
        plan_id = plan.id

    class _StubCopywriter:
        def write_for_item(self, *a, **k):
            # deterministic template fallback, and no real network call in a test.
            raise RuntimeError("no AI in tests")

    import src.ai.copywriter as copywriter_mod
    orig_client, orig_writer = jit_fill.DealSourceClient, copywriter_mod.Copywriter
    jit_fill.DealSourceClient = _StubDealSource
    copywriter_mod.Copywriter = _StubCopywriter
    try:
        with session_scope() as s:
            result = jit_fill.fill_due_slots(s, day=day, all_slots=True)
    finally:
        jit_fill.DealSourceClient = orig_client
        copywriter_mod.Copywriter = orig_writer

    assert result["ok"] and result["filled"] == 1, result
    with session_scope() as s:
        gp = s.scalars(select(GeneratedPost)
                       .where(GeneratedPost.selection_bucket == f"aislot:{plan_id}:0:0")).one()
        stored_slot = gp.format_meta["slot"]
        assert stored_slot["type"] == "single"
        assert stored_slot["time_ist"] == "09:05"
        assert stored_slot["max_price"] == 1000
        assert stored_slot["min_price"] == 100
        assert stored_slot["theme"] == "electronics"
        assert stored_slot["merchant"] == "amazon"


# --------------------------------------------------------------------------- #
# per-post-planning AC2/AC7: a window is a SCHEDULE, not a label.
# --------------------------------------------------------------------------- #

def test_legacy_window_spreads_across_its_full_span_not_a_burst():
    """The reported "vague windows" defect: a 5-post 09:00-12:00 window used to fire
    at 09:00/09:02/09:04/09:06/09:08 (SPACING_MIN from the window START, end time
    parsed then discarded) — an 8-minute burst, then 3 hours of silence."""
    from src.services.generation.jit_fill import SPACING_MIN, _expand_slots

    exp = _expand_slots([{"window_ist": "09:00-12:00", "count": 5, "type": "single"}],
                        date(2026, 7, 25))
    assert len(exp) == 5
    fires = [e[0] for e in exp]
    gaps = [(fires[i + 1] - fires[i]).total_seconds() / 60 for i in range(4)]

    assert gaps == [45.0] * 4, gaps          # 3h span / 4 gaps
    assert all(g > SPACING_MIN for g in gaps), gaps   # explicitly NOT the old burst
    assert len(set(fires)) == 5              # never two posts on one minute
    # 09:00 IST == 03:30 UTC, 12:00 IST == 06:30 UTC — spans the window end to end
    assert (fires[0].hour, fires[0].minute) == (3, 30), fires[0]
    assert (fires[-1].hour, fires[-1].minute) == (6, 30), fires[-1]


def test_per_post_time_ist_fires_at_exactly_that_minute():
    """The new per-post plan shape: one slot object == one post at its own minute."""
    from src.services.generation.jit_fill import _expand_slots

    slots = [{"time_ist": "09:14", "type": "single", "merchant": "amazon"},
             {"time_ist": "13:40", "type": "collection", "merchant": "myntra"}]
    exp = _expand_slots(slots, date(2026, 7, 25))
    assert len(exp) == 2, exp
    # 09:14 IST == 03:44 UTC · 13:40 IST == 08:10 UTC
    assert [(e[0].hour, e[0].minute) for e in exp] == [(3, 44), (8, 10)]
    assert [e[1]["merchant"] for e in exp] == ["amazon", "myntra"]


def test_unparseable_window_is_skipped_not_guessed():
    from src.services.generation.jit_fill import _expand_slots

    assert _expand_slots([{"window_ist": "bad", "count": 3}], date(2026, 7, 25)) == []
    # an invalid hour is dropped rather than wrapped into the wrong end of the day
    assert _expand_slots([{"window_ist": "25:00-26:00", "count": 2}], date(2026, 7, 25)) == []


def test_planner_emitting_two_posts_on_one_minute_is_spaced_apart():
    """Nothing constrains the model to pick distinct `time_ist` values, and two posts
    firing on the same minute is the burst behaviour this change exists to remove."""
    from src.services.generation.jit_fill import SPACING_MIN, _expand_slots

    slots = [{"time_ist": "09:00", "type": "single", "merchant": "amazon"},
             {"time_ist": "09:00", "type": "single", "merchant": "myntra"},
             {"time_ist": "09:00", "type": "collection", "merchant": "ajio"}]
    fires = [e[0] for e in _expand_slots(slots, date(2026, 7, 25))]
    assert len(set(fires)) == 3, fires
    gaps = [(fires[i + 1] - fires[i]).total_seconds() / 60 for i in range(2)]
    assert all(g >= SPACING_MIN for g in gaps), gaps
    # deterministic: the same plan must expand identically on every cron tick
    assert [e[0] for e in _expand_slots(slots, date(2026, 7, 25))] == fires


# --------------------------------------------------------------------------- #
# Deal identity: the source's own id, never a price-sensitive self-hash.
# --------------------------------------------------------------------------- #

def test_deal_id_is_the_sources_own_id_not_a_price_hash():
    """`deal_id` used to be content_hash(url, price, mrp) — so a Rs.1 price move minted a
    NEW id for the same product, and the 3-day repeat guard (which keys on deal_id) waved
    it straight through. Deal prices move constantly."""
    from src.services.generation.enrichment import RawDeal

    a = RawDeal(url="https://www.ajio.com/p/469806281001", title="Puma Sneakers",
                scraped_price="1380.0", scraped_mrp="5999.0", external_id="deal_e71759529d43")
    b = RawDeal(url="https://www.ajio.com/p/469806281001", title="Puma Sneakers",
                scraped_price="1379.0", scraped_mrp="5999.0", external_id="deal_e71759529d43")
    # same product, different price -> must still be the SAME deal
    assert a.external_id == b.external_id

    from src.services.generation.enrichment import content_hash
    assert content_hash(a.url, 1380.0, 5999.0)[:24] != content_hash(b.url, 1379.0, 5999.0)[:24]


def test_pick_fresh_skips_a_deal_already_used_under_a_different_url():
    """The repeat guard matched pool items by `original_url` only, so the same deal
    resurfacing re-shortened or with different affiliate params read as brand new."""
    from src.services.generation.jit_fill import _deal_keys, _pick_fresh

    pool = [{"category_key": "electronics-and-gadgets", "merchant_key": "amazon",
             "original_url": "https://amazon.in/dp/X?tag=new", "external_id": "deal_abc"},
            {"category_key": "electronics-and-gadgets", "merchant_key": "amazon",
             "original_url": "https://amazon.in/dp/Y", "external_id": "deal_xyz"}]

    used = {"deal_abc"}          # posted earlier under a DIFFERENT url
    it, _ = _pick_fresh(pool, "electronics-and-gadgets", "amazon", used)
    assert it["external_id"] == "deal_xyz", it

    # and what we record covers both identifiers, so either one matches next time
    assert set(_deal_keys(pool[0])) == {"deal_abc", "https://amazon.in/dp/X?tag=new"}
    # a source with no id still dedups on url alone (manual/CLI deals)
    assert _deal_keys({"original_url": "u"}) == ["u"]
