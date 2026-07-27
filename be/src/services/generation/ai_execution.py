"""Glue: AI plan -> CampaignPlan row -> deterministic scheduling of real deals.
The AI decides strategy (slots); the deterministic planner fills them from real
inventory. Numbers are fact-checked before the plan is trusted."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.ai.planner import _MIN_TYPE_SHARE, _repair_plan_diversity, _slot_minute
from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan, PlanType
from src.logger import get_logger

logger = get_logger(__name__)


def _parse_date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except (ValueError, TypeError):
        return None


# Absolute daily post ceiling used ONLY on cold start (no posting history to derive a
# data-driven clamp). ~1 post/hour is a safe upper bound for a brand-new channel.
_COLD_START_MAX_POSTS = 24


def _target_type_counts(counts: dict[str, int], target_total: int) -> dict[str, int]:
    """``target_total`` split across the types already present in ``counts``,
    holding their current proportion but clamped to the same ``_MIN_TYPE_SHARE``
    floor the prompt/fallback plan enforce (so reconciliation can never itself
    push a type below the variety floor) — same shape as ``_fallback_day_plan``'s
    loot_share clamp. A single-type plan just gets the whole total."""
    types = list(counts)
    if len(types) < 2:
        return {(types[0] if types else "single"): max(target_total, 0)}
    total = sum(counts.values()) or 1
    shares = {t: counts[t] / total for t in types}
    floor, ceil_ = _MIN_TYPE_SHARE, 1 - _MIN_TYPE_SHARE
    shares = {t: min(max(s, floor), ceil_) for t, s in shares.items()}
    s_total = sum(shares.values()) or 1
    shares = {t: s / s_total for t, s in shares.items()}
    out = {t: max(round(shares[t] * target_total), 0) for t in types}
    drift = target_total - sum(out.values())
    if drift:
        t = max(out, key=lambda x: out[x])
        out[t] = max(out[t] + drift, 0)
    return out


# S1-d — minutes between a duplicated slot and the slot it was copied from (and
# every other duplicate). Well past jit_fill.py's SPACING_MIN (2min) collision
# floor, so a reconciliation-created duplicate reads as its own scheduled post
# instead of the "one brand, dumped all at once, then silence" burst the whole
# per-post-planning spec exists to remove.
_DUP_SPREAD_MIN = 45


def _used_minutes(slots: list[dict]) -> set[int]:
    return {m for m in (_slot_minute(sl) for sl in slots) if m is not None}


def _next_spread_minute(base: int, used: set[int]) -> int:
    """The next minute (wrapping the 24h clock) at least ``_DUP_SPREAD_MIN``
    past ``base`` that no other slot already occupies."""
    minute = (base + _DUP_SPREAD_MIN) % (24 * 60)
    for _ in range(24 * 60 // _DUP_SPREAD_MIN + 1):
        if minute not in used:
            return minute
        minute = (minute + _DUP_SPREAD_MIN) % (24 * 60)
    return minute


def _dedupe_fire_times(slots: list[dict]) -> list[dict]:
    """Guarantee no two per-post slots fire on the same minute. The model — or the
    upstream adjacency repair — can leave two slots at the same ``time_ist``; only
    the duplicate-INSERTION path below spread times, so an exact-count plan (the
    early return in ``_reconcile_per_post_slots``) kept collisions live (two posts
    at 22:00 seen in a real plan). Walk chronologically, keep the first occupant of
    each minute, bump any later collision to the next free spread minute. Only
    touches slots that carry a ``time_ist`` (the per-post shape)."""
    used: set[int] = set()
    for sl in sorted(slots, key=lambda s: (_slot_minute(s) is None, _slot_minute(s) or 0)):
        if not sl.get("time_ist"):
            continue
        m = _slot_minute(sl)
        if m is None:
            continue
        if m in used:
            m = _next_spread_minute(m, used)
            sl["time_ist"] = f"{m // 60:02d}:{m % 60:02d}"
        used.add(m)
    return slots


def _rotation_pool(slots: list[dict], key: str) -> list[str]:
    """Distinct, order-preserving values already present for ``key`` across
    the WHOLE plan (every type) — these are already known-real (validated
    against the live feed by ``parse_plan``'s ``_check_merchants`` / balanced
    by ``ai.planner``'s ``_repair_plan_diversity`` upstream), so duplicates
    rotate through real options instead of only ever repeating the single
    slot they were copied from."""
    return list(dict.fromkeys(sl.get(key) for sl in slots if sl.get(key)))


def _reconcile_per_post_slots(slots: list[dict], target_total: int,
                              feed_pairs: dict[tuple[str, str], int] | None = None) -> list[dict]:
    """AC5 — the per-post shape (one object per post) has no ``count`` to
    rescale, so hitting ``target_total`` means DROPPING or DUPLICATING whole
    slot objects instead. When the count already matches ``target_total``
    this is a no-op (the type-floor rebalance and adjacency repair below only
    run when slots are actually added/removed — a plan that already has the
    right count is left as the model/upstream ``_repair_plan_diversity``
    produced it). Otherwise operates chronologically (``_slot_minute``, shared
    with ``ai.planner``'s adjacency repair) and keeps each type's share within
    ``_MIN_TYPE_SHARE`` of the total via ``_target_type_counts``. Dropping
    removes the chronologically LATEST occurrences of an over-quota type first
    (front-loaded posts survive); duplicating an under-quota type appends
    copies of its last occurrence, but each copy gets its OWN spread fire time
    (``_next_spread_minute``) and rotates merchant/theme through real values
    — a bare ``dict(have[-1])`` repeat would re-create S1-d (same time/
    merchant/theme, collision-floor-packed a couple minutes apart). A final
    stable chronological sort places every slot, original or duplicate, in
    fire-time order.

    ``feed_pairs`` (optional — ``ai.planner._feed_pairs``'s ``{(merchant,
    category): live_deal_count}``) is the live feed's own stock, threaded
    down from ``generate_day_plan``. When given, a duplicate's (merchant,
    theme) is chosen as a PAIR from this real stock (deepest-stocked first,
    never assigning a pairing more slots than it has deals until every
    pairing is saturated — never stranding a slot) instead of rotating
    merchant and theme through two INDEPENDENT pools (``_rotation_pool``),
    which can recombine them into a pairing the feed stocks zero of (e.g.
    myntra+electronics) — an unfillable slot ``jit_fill`` can only satisfy by
    broadening to a different merchant, re-creating the one-merchant-window
    defect this whole rotation exists to avoid. Without ``feed_pairs`` (the
    two existing call paths — legacy callers, tests) this falls back to the
    old independent-pool rotation unchanged."""
    ordered = sorted(slots, key=lambda sl: (_slot_minute(sl) is None, _slot_minute(sl) or 0))
    if len(ordered) == target_total:
        return _dedupe_fire_times(ordered)
    counts = Counter(sl.get("type") or "single" for sl in ordered)
    desired = _target_type_counts(dict(counts), target_total)
    merchants = _rotation_pool(ordered, "merchant")
    themes = _rotation_pool(ordered, "theme")
    # Deepest-stocked pairs first — the pair walk's own preference (ai.planner._pair_sequence).
    pair_seq = sorted(feed_pairs, key=lambda p: (-feed_pairs[p], p)) if feed_pairs else None
    pair_used: dict[tuple[str, str], int] = {}
    if pair_seq:
        for sl in ordered:
            p = (sl.get("merchant"), sl.get("theme"))
            if p[0] and p[1]:
                pair_used[p] = pair_used.get(p, 0) + 1
    out = list(ordered)
    for t, want in desired.items():
        have = [sl for sl in out if (sl.get("type") or "single") == t]
        if len(have) > want:
            drop_ids = {id(sl) for sl in have[want:]}  # drop the latest occurrences
            out = [sl for sl in out if id(sl) not in drop_ids]
        elif len(have) < want and have:
            used = _used_minutes(out)
            base = _slot_minute(have[-1])
            src_merchant, src_theme = have[-1].get("merchant"), have[-1].get("theme")
            src_pair = (src_merchant, src_theme)
            m_start = merchants.index(src_merchant) + 1 if src_merchant in merchants else 0
            th_start = themes.index(src_theme) + 1 if src_theme in themes else 0
            p_start = (pair_seq.index(src_pair) + 1) if pair_seq and src_pair in pair_seq else 0
            for i in range(want - len(have)):
                dup = dict(have[-1])
                rotated: list[str] = []
                if pair_seq:
                    # Next pairing (starting just past the source's own) with headroom
                    # left in the feed; if every pairing is already saturated, reuse the
                    # next one in rotation anyway — a repeated-but-fillable slot beats an
                    # unfillable one, and both beat a missing one.
                    pair = next(
                        (pair_seq[(p_start + i + j) % len(pair_seq)] for j in range(len(pair_seq))
                         if pair_used.get(pair_seq[(p_start + i + j) % len(pair_seq)], 0)
                            < feed_pairs[pair_seq[(p_start + i + j) % len(pair_seq)]]),
                        pair_seq[(p_start + i) % len(pair_seq)])
                    pair_used[pair] = pair_used.get(pair, 0) + 1
                    dup["merchant"], dup["theme"] = pair
                    if dup["merchant"] != src_merchant:
                        rotated.append("merchant")
                    if dup["theme"] != src_theme:
                        rotated.append("theme")
                else:
                    if len(merchants) >= 2:
                        dup["merchant"] = merchants[(m_start + i) % len(merchants)]
                        if dup["merchant"] != src_merchant:
                            rotated.append("merchant")
                    if len(themes) >= 2:
                        dup["theme"] = themes[(th_start + i) % len(themes)]
                        if dup["theme"] != src_theme:
                            rotated.append("theme")
                if base is not None:
                    base = _next_spread_minute(base, used)
                    used.add(base)
                    dup["time_ist"] = f"{base // 60:02d}:{base % 60:02d}"
                else:
                    # Source slot's time_ist didn't parse — the duplicate inherits
                    # that same unparseable time_ist and _slot_fire_times will never
                    # fire it, so this inflates the day's planned count without
                    # posting anything. Nothing else logs this; flag it here.
                    logger.warning(
                        "[ai_execution] reconciliation duplicated a slot with no "
                        "parseable time_ist (type=%s, merchant=%s) — it will never fire",
                        t, dup.get("merchant"),
                    )
                if rotated:
                    # The source slot's `why` was grounded in stats for the OLD
                    # merchant/theme — keeping it (even appended-to) leaves prose
                    # naming a merchant/stat that no longer matches `dup["merchant"]`.
                    # Replace with a number-free rotation note, same precedent as
                    # planner._repair_plan_diversity's own reassignment rewrite.
                    dup["why"] = (
                        f"{dup.get('merchant') or 'Deal'} · {dup.get('theme') or 'general'} "
                        "post — spread across the day for reach and variety; "
                        f"{' and '.join(rotated)} varied so it doesn't repeat the "
                        "previous slot's pick."
                    )
                else:
                    # Neither field rotated (fewer than 2 real options for that
                    # dimension) — the source `why` still describes this slot's
                    # actual merchant/theme, so it stays accurate.
                    dup["why"] = (
                        f"{(have[-1].get('why') or '').rstrip()} "
                        "(additional post spread across the day for coverage.)"
                    ).strip()
                out.append(dup)
    out = sorted(out, key=lambda sl: (_slot_minute(sl) is None, _slot_minute(sl) or 0))
    # Each type is reconciled independently above, then interleaved by the sort — so two
    # slots from DIFFERENT type groups can still land adjacent with the same merchant even
    # though neither group repeated internally. Re-run the planner's adjacency repair on the
    # final chronological order, which is the only place that ordering exists. The pools are
    # the plan's own values (already validated against the live feed upstream by
    # _check_merchants/_repair_plan_diversity), so this can't invent a merchant jit_fill
    # could never fill.
    # Constrain the repair to real (merchant, theme) pairs. Passing only the flat
    # merchant/theme pools would let it recombine them freely and land on a pairing
    # the feed can't stock (myntra + electronics — 0 deals), and an unfillable slot
    # falls through jit_fill's broadening tiers, which is the one-merchant-window
    # defect re-entering a layer up. Prefer the real live-feed stock (``feed_pairs``,
    # with counts, so the repair can ALSO honour depth) when it was threaded down;
    # otherwise fall back to the plan's own pairs (valid by construction — the
    # duplicates above were built from them too when no feed_pairs was given).
    _repair_plan_diversity(
        out, _rotation_pool(out, "merchant"), _rotation_pool(out, "theme"),
        available_pairs=feed_pairs or (
            {(sl.get("merchant"), sl.get("theme")) for sl in out
             if sl.get("merchant") and sl.get("theme")} or None))
    return _dedupe_fire_times(out)


def _rescale_slot_counts(plan: dict, target_total: int,
                         feed_pairs: dict[tuple[str, str], int] | None = None) -> None:
    """G10 — reconcile ``post_slots`` (in place) to exactly ``target_total``
    posts, whatever the model/fallback proposed. jit_fill reads ``post_slots``
    directly to decide how many posts to actually make, so without this the
    clamp only ever changed the DISPLAYED recommended_posts — the executed
    plan stayed at the model's raw (unclamped) total. Two shapes:
    - LEGACY (a slot literally carries a ``count`` field — several posts share
      one window object): rescale each slot's ``count`` proportionally, same
      as before — jit_fill's legacy path reads ``count`` directly.
    - PER-POST (the new shape — one post per object, no ``count`` field):
      rescaling a count would silently reintroduce the old multi-post-per-
      object shape, so whole objects are dropped/duplicated instead
      (``_reconcile_per_post_slots``) — never a count bump.
    Never leaves the plan at zero slots even if ``target_total`` is 0/negative
    — the day must never go silent. ``feed_pairs`` (optional — the live feed's
    ``(merchant, category) -> deal count``, threaded down from
    ``ai.planner.generate_day_plan``'s returned ``result["feed_pairs"]``) is
    forwarded to ``_reconcile_per_post_slots`` so a PER-POST duplicate is
    built from real stock instead of two independent merchant/theme pools."""
    slots = plan.get("post_slots") or []
    if not slots or target_total is None:
        return
    target_total = max(int(target_total), 1)  # never reduce the day to zero posts
    if any("count" in sl for sl in slots):
        raw_total = sum(max(int(sl.get("count") or 0), 0) for sl in slots)
        if raw_total <= 0 or raw_total == target_total:
            return
        scaled = [max(round((sl.get("count") or 0) * target_total / raw_total), 0) for sl in slots]
        if sum(scaled) == 0:
            scaled[0] = 1
        drift = target_total - sum(scaled)
        if drift:
            i = max(range(len(scaled)), key=lambda k: scaled[k])
            scaled[i] = max(scaled[i] + drift, 0)
        for sl, c in zip(slots, scaled):
            sl["count"] = c
        return
    plan["post_slots"] = _reconcile_per_post_slots(slots, target_total, feed_pairs)


def persist_ai_plan(
    s: Session, result: dict,
    recent_median: int | None = None, recent_max_30d: int | None = None,
) -> CampaignPlan | None:
    """``recent_median``/``recent_max_30d`` are the same clamp bounds
    ``daily_brief`` uses for DISPLAY (``ctx.clamp_recommended_posts``) — passing
    them here applies that clamp at PERSIST time too (G10), so the stored
    blueprint jit_fill executes matches what's shown instead of drifting from it.
    ``result["feed_pairs"]`` (``ai.planner.generate_day_plan``'s live-feed
    ``(merchant, category) -> deal count``, absent on older/synthetic ``result``
    dicts) is forwarded to the reconciliation so a duplicated slot can't be
    scheduled onto a pairing the feed doesn't stock."""
    if not result.get("available") or not result.get("plan"):
        return None
    plan = result["plan"]
    rec = plan.get("recommended_posts")
    if rec is not None:
        if recent_median is not None:
            from src.ai.context import clamp_recommended_posts
            clamped, was_clamped = clamp_recommended_posts(rec, recent_median, recent_max_30d)
            # Record the outcome IN the blueprint so daily_brief (and cache-hit reads)
            # can surface "we clipped the AI's number" without re-deriving it from the
            # already-clamped value — re-clamping a clamped number always looks in-range.
            plan["plan_clamped"] = was_clamped
            if was_clamped:
                plan["recommended_posts"] = rec = clamped
        elif rec > _COLD_START_MAX_POSTS:
            # Cold start (no history -> no data-driven clamp bounds). The clamp used to be
            # skipped entirely here, so the model's raw count (e.g. 71) persisted AND
            # executed. Apply an absolute safety ceiling instead of trusting it blindly.
            # ponytail: fixed cold-start cap; superseded by the data-driven clamp the
            # moment any posting history exists.
            plan["recommended_posts"] = rec = _COLD_START_MAX_POSTS
            plan["plan_clamped"] = True
        # Reconcile slot counts to the final recommended_posts ALWAYS (every path, incl.
        # cold start): the model routinely lets post_slots' counts drift from its own
        # stated recommended_posts, and jit_fill executes the slot counts — so without
        # this the day would post the drifted total (e.g. 71) instead of the cadence.
        _rescale_slot_counts(plan, rec, result.get("feed_pairs"))
    fc = result.get("factcheck", {"status": "skipped"})
    target_date = _parse_date(plan.get("date"))
    row = CampaignPlan(
        plan_type=PlanType.DAILY,
        title=f"AI day plan {plan.get('date') or ''}".strip(),
        target_date=target_date,
        blueprint=plan,
        expected_outcome={"emphasis": plan.get("emphasis"), "watch": plan.get("watch")},
        confidence={"passed": 0.6, "warn": 0.45, "fallback": 0.2}.get(fc.get("status"), 0.3),
        generated_at=datetime.now(timezone.utc),
        is_ai_generated=True,
        ai_digest=result.get("digest", ""),
        cited_numbers=plan.get("cited_numbers", []),
        factcheck_status=fc.get("status", "skipped"),
        report_ids=result.get("report_ids", []),
    )
    try:
        # SAVEPOINT: on a unique-constraint violation we only need to unwind this
        # insert, not the whole (mostly read-only) outer transaction the caller may
        # still be using (e.g. daily_brief() building the rest of its response).
        with s.begin_nested():
            s.add(row)
            s.flush()
        return row
    except IntegrityError:
        # Two near-simultaneous requests for the same day both missed the cache and
        # both tried to persist an AI plan — the unique index on (campaign_version,
        # plan_type, target_date, is_ai_generated) rejects the loser. Don't 500:
        # the winner's row already has everything we need, so use it instead.
        logger.info(
            "[ai_execution] concurrent AI plan insert lost the race for target_date=%s "
            "— reusing the row the other request just persisted", target_date,
        )
        existing = s.scalars(
            select(CampaignPlan)
            .where(CampaignPlan.campaign_version == CAMPAIGN_VERSION,
                   CampaignPlan.plan_type == PlanType.DAILY,
                   CampaignPlan.target_date == target_date,
                   CampaignPlan.is_ai_generated == True)  # noqa: E712
            .order_by(CampaignPlan.generated_at.desc())
        ).first()
        return existing


def persist_weekly_plan(
    s: Session, week_start: date, week_end: date, blueprint: dict,
    digest: str = "", is_ai_generated: bool = False,
) -> CampaignPlan | None:
    """Insert a fresh WEEKLY ``CampaignPlan`` row keyed by calendar week (Monday
    ``week_start``) — the create-path ``weekly_brief()`` was missing (it could
    only ever UPDATE a row that already existed, never make one).

    ``blueprint`` is expected to already carry the AI's parsed ``loot_deal_ratio``/
    ``merchant_priorities``/``daily_themes`` merged in (G1) — the caller
    (``_weekly_ai_generate``) does that merge, since it's the one place both the
    deterministic skeleton and the AI's parsed plan are in scope together."""
    row = CampaignPlan(
        plan_type=PlanType.WEEKLY,
        title=f"Weekly plan — week of {week_start.isoformat()}",
        target_date=week_start,
        end_date=week_end,
        blueprint=blueprint,
        confidence=0.6,
        generated_at=datetime.now(timezone.utc),
        is_ai_generated=is_ai_generated,
        ai_digest=digest or None,
    )
    try:
        # Same SAVEPOINT pattern as persist_ai_plan: a losing insert only unwinds
        # itself, not the caller's outer (mostly read-only) transaction.
        with s.begin_nested():
            s.add(row)
            s.flush()
        return row
    except IntegrityError:
        # A row for this (week, is_ai_generated) already exists. UPDATE it in place with
        # the fresh blueprint/digest instead of returning the STALE one — otherwise a
        # re-run (or a concurrent request) silently dropped the AI's loot_ratio/
        # merchant_priorities/daily_themes and the daily planner read Nones (data_flow G1).
        logger.info(
            "[ai_execution] weekly plan row exists for week_start=%s — updating in place "
            "with the fresh blueprint", week_start,
        )
        existing = s.scalars(
            select(CampaignPlan)
            .where(CampaignPlan.campaign_version == CAMPAIGN_VERSION,
                   CampaignPlan.plan_type == PlanType.WEEKLY,
                   CampaignPlan.target_date == week_start,
                   CampaignPlan.is_ai_generated == is_ai_generated)
            .order_by(CampaignPlan.generated_at.desc())
        ).first()
        if existing is not None:
            existing.blueprint = blueprint
            existing.end_date = week_end
            existing.confidence = 0.6
            existing.generated_at = datetime.now(timezone.utc)
            if digest:
                existing.ai_digest = digest
            s.flush()
        return existing


def _demo() -> None:
    """Runnable self-check (no DB): AC5 count reconciliation on both slot shapes."""
    # LEGACY shape (a `count` field present) rescales in place, same as before.
    legacy = {"post_slots": [{"type": "single", "window_ist": "09:00-12:00", "count": 6},
                             {"type": "collection", "window_ist": "18:00-21:00", "count": 3}]}
    _rescale_slot_counts(legacy, 6)
    assert sum(sl["count"] for sl in legacy["post_slots"]) == 6

    # PER-POST shape (no `count`) drops whole objects to reach a smaller target,
    # keeps chronological order, and keeps both types above the 30% floor.
    per_post = {"post_slots": [
        {"type": "single", "time_ist": f"{9 + i:02d}:00", "merchant": "amazon"}
        for i in range(6)
    ] + [
        {"type": "collection", "time_ist": f"{18 + i:02d}:00", "merchant": "ajio"}
        for i in range(4)
    ]}
    _rescale_slot_counts(per_post, 5)
    slots = per_post["post_slots"]
    assert len(slots) == 5, slots
    assert all("count" not in sl for sl in slots)
    times = [sl["time_ist"] for sl in slots]
    assert times == sorted(times), times  # chronological order preserved
    counts = Counter(sl["type"] for sl in slots)
    assert min(counts.values()) / len(slots) >= _MIN_TYPE_SHARE - 1e-9, counts

    # PER-POST shape DUPLICATES objects to reach a larger target, total exact,
    # never reduces the day to zero even if target is 0. S1-d: duplicates must
    # NOT all land on the source slot's time/merchant/theme (the reported
    # "one brand dumped at once" burst) — each gets its own spread time and a
    # rotated merchant/theme.
    small = {"post_slots": [
        {"type": "single", "time_ist": "09:00", "merchant": "amazon", "theme": "electronics"},
        {"type": "collection", "time_ist": "18:00", "merchant": "ajio", "theme": "fashion"},
    ]}
    _rescale_slot_counts(small, 7)
    dup_slots = small["post_slots"]
    assert len(dup_slots) == 7
    dup_times = [sl["time_ist"] for sl in dup_slots]
    assert len(set(dup_times)) == len(dup_times), dup_times
    assert all(dup_slots[i]["merchant"] != dup_slots[i + 1]["merchant"]
              for i in range(len(dup_slots) - 1)), dup_slots

    zeroed = {"post_slots": [{"type": "single", "time_ist": "09:00", "merchant": "amazon"}]}
    _rescale_slot_counts(zeroed, 0)
    assert len(zeroed["post_slots"]) >= 1  # never an empty day

    print("services/generation/ai_execution.py self-check OK")


if __name__ == "__main__":
    _demo()
