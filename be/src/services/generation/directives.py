"""Turn a free-text operator STEER directive into HARD, deterministic constraints and
enforce them on a day's slots.

The AI reads the directive too (it shapes the narrative and the loot/single lean), but
the AI can't be trusted to actually *restrict* the schedule — the deterministic
diversity-repair downstream happily re-introduces merchants the operator asked to drop.
So a directive like "Focus on Amazon and Flipkart only" or "post only in the evening"
must be parsed into a structured constraint and applied deterministically.

Nothing here is hallucinated: merchants/categories are matched ONLY against the real
feed values passed in, and times only from explicit clock expressions. A constraint the
feed can't fully satisfy is APPLIED as far as possible and REPORTED (an honest note),
never silently dropped."""
from __future__ import annotations

import re

# Time-of-day words -> [start_min, end_min) since midnight. Overlapping words widen
# the window (min start, max end); an explicit clock time narrows it (see below).
_TIME_WORDS = {
    "late night": (22 * 60, 24 * 60),
    "morning": (6 * 60, 12 * 60),
    "afternoon": (12 * 60, 17 * 60),
    "evening": (17 * 60, 24 * 60),
    "night": (20 * 60, 24 * 60),
}
# Cues that turn a merchant/category MENTION into a hard allow-list. Without one of
# these ("post more loot", "push electronics") the mention is a soft lean the AI
# handles — only an explicit restriction ("only", "just X") pins the schedule.
_RESTRICT_CUES = ("only", "just", "focus on", "stick to", "limit to", "exclusively",
                  "nothing but", "solely")


def _mentions(text: str, slug: str) -> bool:
    """True if the directive names this feed slug — any significant word of the slug
    ("electronics" of "electronics-and-gadgets") as a whole word in the text."""
    words = [w for w in re.split(r"[^a-z0-9]+", slug.lower())
             if len(w) > 2 and w not in ("and", "the", "for")]
    return bool(words) and any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def _hm(hour: str, minute: str | None, ampm: str | None) -> int:
    """(hour, minute, am/pm) -> minutes since midnight. No am/pm is read as a 24h
    clock ('18:00' -> 1080), so '6pm' and '18:00' both resolve to 18:00."""
    h = int(hour)
    if ampm == "pm":
        h = (h % 12) + 12
    elif ampm == "am":
        h = h % 12
    return min(h, 24) * 60 + (int(minute) if minute else 0)


def _parse_time_window(t: str) -> tuple[int | None, int | None]:
    """(after_min, before_min) — the earliest/latest a post may fire, or None when the
    directive doesn't bound that side. Word windows set both; explicit clock phrases
    ('after 6pm', '6pm onwards', 'before 9pm') tighten the relevant side."""
    after = before = None
    for word, (lo, hi) in _TIME_WORDS.items():
        if word in t:
            after = lo if after is None else min(after, lo)
            before = hi if before is None else max(before, hi)
    for m in re.finditer(r"\b(?:after|from|past|since)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t):
        after = max(after or 0, _hm(m.group(1), m.group(2), m.group(3)))
    for m in re.finditer(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+onwards?\b", t):
        after = max(after or 0, _hm(m.group(1), m.group(2), m.group(3)))
    for m in re.finditer(r"\b(?:before|until|till|by)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t):
        b = _hm(m.group(1), m.group(2), m.group(3))
        before = b if before is None else min(before, b)
    return after, before


def parse_directive_constraints(directive: str | None,
                                available_merchants: list[str] | None = None,
                                available_categories: list[str] | None = None) -> dict:
    """Free-text directive -> {merchants, categories, after_min, before_min}. Each is
    None when unconstrained. merchants/categories are populated ONLY when the directive
    both names real feed values AND carries a restriction cue ('only'/'focus on'…)."""
    out = {"merchants": None, "categories": None, "after_min": None, "before_min": None}
    if not directive:
        return out
    t = directive.lower()
    if any(cue in t for cue in _RESTRICT_CUES):
        named_m = [m for m in (available_merchants or []) if _mentions(t, m)]
        if named_m:
            out["merchants"] = set(named_m)
        named_c = [c for c in (available_categories or []) if _mentions(t, c)]
        if named_c:
            out["categories"] = set(named_c)
    out["after_min"], out["before_min"] = _parse_time_window(t)
    return out


def _cats_by_merchant(feed_pairs: dict | None) -> dict[str, set]:
    out: dict[str, set] = {}
    for (m, c) in (feed_pairs or {}):
        out.setdefault(m, set()).add(c)
    return out


def _steer_why(sl: dict, reason: str) -> str:
    return f"{sl.get('merchant')} · {sl.get('theme')} post — {reason}."


def enforce_pair_constraints(slots: list[dict], constraints: dict,
                             feed_pairs: dict | None) -> list[str]:
    """Pin slots to the directive's allowed merchants AND categories JOINTLY, IN PLACE.

    ONE constraint step, not a pass per dimension: build the set of (merchant, category)
    pairs the feed actually stocks that satisfy BOTH allow-lists at once, then give every
    slot whose current pair is disallowed a valid one (rotated for merchant/theme variety,
    deepest-stocked pairs first). This adapts to any combination — merchant-only,
    category-only, both, or neither — and can't undo itself the way separate merchant-
    then-category passes did. Every result is a real feed pair jit_fill can fill.

    Honest note when the combined constraint is UNSATISFIABLE (the feed has no pair
    matching both) — slots are left as-is rather than silently faked."""
    allowed_m = constraints.get("merchants")
    allowed_c = constraints.get("categories")
    if not allowed_m and not allowed_c:
        return []
    pairs = feed_pairs or {}
    valid = [(m, c) for (m, c) in pairs
             if (not allowed_m or m in allowed_m) and (not allowed_c or c in allowed_c)]
    if not valid:
        want = []
        if allowed_m:
            want.append("merchants " + "/".join(sorted(allowed_m)))
        if allowed_c:
            want.append("categories " + "/".join(sorted(allowed_c)))
        return [f"today's feed has no deals matching your steer ({' + '.join(want)}), "
                "so slots were left unchanged"]

    valid_set = set(valid)
    ranked = sorted(valid, key=lambda p: (-pairs.get(p, 0), p))  # deepest stock first
    changed, j = 0, 0
    for i, sl in enumerate(slots):
        if (sl.get("merchant"), sl.get("theme")) in valid_set:
            continue  # already satisfies the steer — leave the AI's pick
        prev_m = slots[i - 1].get("merchant") if i else None
        prev_c = slots[i - 1].get("theme") if i else None
        pick = None
        for k in range(len(ranked)):  # prefer a pair repeating neither neighbour field
            cand = ranked[(j + k) % len(ranked)]
            if cand[0] != prev_m and cand[1] != prev_c:
                pick, j = cand, (j + k + 1) % len(ranked)
                break
        if pick is None:
            pick, j = ranked[j % len(ranked)], (j + 1) % len(ranked)
        sl["merchant"], sl["theme"] = pick
        sl["why"] = _steer_why(sl, "pinned to your steer")
        changed += 1
    if changed:
        want = []
        if allowed_m:
            want.append("merchants " + "/".join(sorted(allowed_m)))
        if allowed_c:
            want.append("categories " + "/".join(sorted(allowed_c)))
        return [f"{changed} slot(s) reassigned to honor your steer ({'; '.join(want)})"]
    return []


def _demo() -> None:
    """Runnable self-check (no DB): parsing pins only on a restriction cue, matches
    real feed slugs, reads clock windows; enforcement keeps pairs feed-valid."""
    feed = {("amazon", "electronics-and-gadgets"): 5, ("flipkart", "electronics-and-gadgets"): 6,
            ("flipkart", "fashion-and-lifestyle"): 3, ("ajio", "fashion-and-lifestyle"): 5,
            ("myntra", "general"): 1}
    merch = ["ajio", "amazon", "flipkart", "myntra"]
    cats = ["electronics-and-gadgets", "fashion-and-lifestyle", "general"]

    # a plain lean (no cue) does NOT pin merchants...
    assert parse_directive_constraints("post more loot boards", merch, cats)["merchants"] is None
    # ...but "focus on amazon and flipkart only" does, matched to real slugs.
    c = parse_directive_constraints("Focus on Amazon and Flipkart only", merch, cats)
    assert c["merchants"] == {"amazon", "flipkart"}, c
    # "push electronics" is a lean; "only electronics" pins the category.
    assert parse_directive_constraints("push electronics hard", merch, cats)["categories"] is None
    assert parse_directive_constraints("post only electronics deals", merch, cats)["categories"] \
        == {"electronics-and-gadgets"}
    # time windows: word + explicit clock, tighter side wins.
    a, b = _parse_time_window("post only in the evening, 6pm onwards")
    assert a == 18 * 60 and b == 24 * 60, (a, b)
    assert _parse_time_window("before 9pm") == (None, 21 * 60)

    # enforcement: ajio/myntra slots must move to amazon/flipkart, pairs stay valid.
    slots = [
        {"merchant": "ajio", "theme": "fashion-and-lifestyle", "why": "x"},
        {"merchant": "myntra", "theme": "general", "why": "x"},
        {"merchant": "amazon", "theme": "electronics-and-gadgets", "why": "x"},
    ]
    enforce_pair_constraints(slots, {"merchants": {"amazon", "flipkart"}}, feed)
    assert all(sl["merchant"] in {"amazon", "flipkart"} for sl in slots), slots
    assert all((sl["merchant"], sl["theme"]) in feed for sl in slots), slots  # feed-valid

    # THE JOINT case that broke the old two-pass version: merchant AND category together.
    both = [{"merchant": "ajio", "theme": "fashion-and-lifestyle", "why": "x"},
            {"merchant": "myntra", "theme": "general", "why": "x"}]
    enforce_pair_constraints(both, {"merchants": {"amazon", "flipkart"},
                                    "categories": {"electronics-and-gadgets"}}, feed)
    # every slot must satisfy BOTH — merchant in {amazon,flipkart} AND category electronics.
    assert all(sl["merchant"] in {"amazon", "flipkart"} for sl in both), both
    assert all(sl["theme"] == "electronics-and-gadgets" for sl in both), both

    # unsatisfiable combo (myntra only stocks 'general'; no electronics) -> honest note.
    imp = [{"merchant": "amazon", "theme": "electronics-and-gadgets", "why": "x"}]
    note = enforce_pair_constraints(imp, {"merchants": {"myntra"},
                                          "categories": {"electronics-and-gadgets"}}, feed)
    assert note and "no deals matching" in note[0], note
    print("services/generation/directives.py self-check OK")


if __name__ == "__main__":
    _demo()