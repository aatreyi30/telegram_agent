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


# Cues that turn a merchant/category MENTION into a hard EXCLUSION ("avoid amazon",
# "no fashion", "skip electronics"). Phrase-scoped (the cue must sit a few words before
# the slug) so "focus on amazon, avoid ajio" excludes only ajio, not amazon.
_EXCLUDE_CUE_RE = r"(?:avoid|exclude|skip|without|drop|no|not|don'?t|nothing from)"


def _excluded(text: str, slug: str) -> bool:
    """True if the directive asks to EXCLUDE this feed slug — an exclusion cue within a
    few words before a significant word of the slug. Same word-splitting as `_mentions`."""
    words = [w for w in re.split(r"[^a-z0-9]+", slug.lower())
             if len(w) > 2 and w not in ("and", "the", "for")]
    return bool(words) and any(
        re.search(rf"\b{_EXCLUDE_CUE_RE}\b(?:\s+\w+){{0,3}}\s+{re.escape(w)}\b", text)
        for w in words)


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


# Common merchant shorthands/abbreviations an operator types that regex-matching the
# exact feed slug would miss. Only canonicalized when the canonical merchant is actually
# in today's feed (so we never inject a merchant that isn't stocked).
_MERCHANT_ALIASES = {
    "amazon": ("amzn", "amazonin", "amazon.in", "amzn.in", "amazone", "amzon"),
    "flipkart": ("flip", "fk", "flpkart", "flipcart", "flipkrt", "flpkrt", "flipcard"),
    "myntra": ("myntr", "mynta", "myntraa"),
    "ajio": ("ajio.com", "aajio"),
}


# Clear PAUSE intents ("pause posting", "don't post today", "stop posting"). Kept
# deliberately narrow: the general object (posting/today/anything/at all) must follow the
# stop-verb, so "don't post electronics" is an EXCLUSION, not a pause.
_PAUSE_RE = re.compile(
    r"\b(?:pause|stop|halt|freeze|hold(?:\s*off)?)\s+(?:the\s+)?"
    r"(?:post|posts|posting|publishing|channel|plan|everything|all(?:\s+posts?)?|today)\b"
    r"|\b(?:do\s*n['o]?t|don'?t|dont)\s+post(?:ing|s)?\s+(?:today|anything|everything|at\s+all)\b"
    r"|\bno\s+post(?:s|ing)?\s+(?:today|at\s+all)\b"
    r"|\bskip\s+(?:posting\s+)?today\b")

_PAUSE_EXACT = frozenset({
    "pause", "stop", "halt", "freeze", "stop posting", "pause posting", "pause today",
    "no posts today", "skip today", "don't post today", "dont post today",
    "hold posting", "pause the channel"})


def parse_pause(directive: str | None) -> bool:
    """True if the directive is a clear request to PAUSE/stop posting (not a content
    steer). Handled specially by the caller — steering reshapes the plan but can't stop
    the live queue, so a pause must NOT be silently reinterpreted as a normal plan."""
    if not directive:
        return False
    t = directive.strip().lower()
    return t in _PAUSE_EXACT or bool(_PAUSE_RE.search(t))


def _canonicalize_merchants(t: str, available_merchants: list[str] | None) -> str:
    """Rewrite merchant shorthands/typos in ``t`` to the canonical feed slug, so 'amzn'
    or 'flipkrt' still pins/excludes the right merchant. Static aliases handle
    abbreviations; a strict difflib pass (cutoff 0.85, 4+ chars) handles misspellings —
    both restricted to merchants ACTUALLY in today's feed so nothing unstocked is
    injected."""
    import difflib

    avail = {m.lower() for m in (available_merchants or [])}
    if not avail:
        return t
    for canon, aliases in _MERCHANT_ALIASES.items():
        if canon in avail:
            for a in aliases:
                t = re.sub(rf"\b{re.escape(a)}\b", canon, t)
    for tok in set(re.findall(r"[a-z0-9.]+", t)):
        if len(tok) < 4 or tok in avail:
            continue
        # 5+ chars tolerate a looser 0.8 (catches more typos); 4-char tokens keep the
        # strict 0.85 (short words false-match too easily, e.g. 'audio'~'ajio').
        cutoff = 0.8 if len(tok) >= 5 else 0.85
        match = difflib.get_close_matches(tok, avail, n=1, cutoff=cutoff)
        if match:
            t = re.sub(rf"\b{re.escape(tok)}\b", match[0], t)
    return t


# Price-tier cues -> rupee bound. Two-digit minimum (\d{2,6}) dodges single-digit clock
# times ('from 6pm'); the band form additionally requires both sides >= 50 so a time
# span like '18:00-21:00' can't be misread as a price band.
_PRICE_UNDER_RE = re.compile(r"(?:under|below|less than|upto|up to|max|maximum|within)\s*(?:rs\.?|inr|₹)?\s*(\d{2,6})")
# Note: 'from'/'starting' are deliberately NOT price cues — the time parser owns 'from'
# ('from 6pm'), so sharing it would let a price steer set a bogus time window.
_PRICE_OVER_RE = re.compile(r"(?:over|above|more than|at least|minimum|min)\s*(?:rs\.?|inr|₹)?\s*(\d{2,6})")
_PRICE_BAND_RE = re.compile(r"(?:rs\.?|inr|₹)?\s*(\d{2,6})\s*(?:-|to|–|and)\s*(?:rs\.?|inr|₹)?\s*(\d{2,6})")


def _parse_price_window(t: str) -> tuple[int | None, int | None]:
    """(min_price, max_price) rupee bounds from the directive, or None per side."""
    mb = _PRICE_BAND_RE.search(t)
    if mb:
        a, b = int(mb.group(1)), int(mb.group(2))
        if min(a, b) >= 50:   # both sides look like prices, not clock digits
            return min(a, b), max(a, b)
    lo = hi = None
    mu = _PRICE_UNDER_RE.search(t)
    if mu:
        hi = int(mu.group(1))
    mo = _PRICE_OVER_RE.search(t)
    if mo:
        lo = int(mo.group(1))
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo   # contradictory bounds ('over 1500 under 500') -> a sane band
    return lo, hi


_TARGET_POSTS_RE = re.compile(
    r"\b(?:post|publish|schedule|put out|send|do|run|make it|set to|change to|reduce to|"
    r"increase to|bump to|down to|up to)\s+"
    r"(?:only\s+|just\s+|about\s+|around\s+|roughly\s+)?(\d{1,3})\b"
    r"|\b(\d{1,3})\s+posts?\b")
# A number the operator is moving AWAY from ("don't want 39", "not 39", "instead of 39")
# is the OLD count, never the target — exclude it.
_REJECTED_COUNT_RE = re.compile(
    r"(?:don'?t\s+want|do\s+not\s+want|instead\s+of|rather\s+than|not)\s+(\d{1,3})")


def parse_target_posts(directive: str | None) -> int | None:
    """The desired post count from a quantity steer, or None when none is named. Handles
    a correction like 'I don't want 39, make it 30' — the REJECTED number (39) is dropped
    and the LAST remaining candidate wins (a correction comes later in the sentence).
    Bounded to 1..350; a downstream safety clamp still caps it against recent cadence.
    Parse the RAW ask, NEVER the composed blob ('N posts already live')."""
    if not directive:
        return None
    t = directive.lower()
    rejected = {int(x) for x in _REJECTED_COUNT_RE.findall(t)}
    cands = [int(g1 or g2) for g1, g2 in _TARGET_POSTS_RE.findall(t)]
    cands = [n for n in cands if 1 <= n <= 350 and n not in rejected]
    return cands[-1] if cands else None


def parse_directive_constraints(directive: str | None,
                                available_merchants: list[str] | None = None,
                                available_categories: list[str] | None = None) -> dict:
    """Free-text directive -> {merchants, categories, exclude_merchants,
    exclude_categories, after_min, before_min}. Each is None when unconstrained.
    merchants/categories (the ALLOW-list) are populated only when the directive both
    names real feed values AND carries a restriction cue ('only'/'focus on'…);
    exclude_* (the DENY-list) when an exclusion cue ('avoid'/'no'/'skip'…) names one."""
    out = {"merchants": None, "categories": None,
           "exclude_merchants": None, "exclude_categories": None,
           "after_min": None, "before_min": None,
           "price_min": None, "price_max": None}
    if not directive:
        return out
    t = _canonicalize_merchants(directive.lower(), available_merchants)
    avail_m, avail_c = available_merchants or [], available_categories or []
    excl_m = {m for m in avail_m if _excluded(t, m)}
    excl_c = {c for c in avail_c if _excluded(t, c)}
    if any(cue in t for cue in _RESTRICT_CUES):
        # An include-cue mention that's ALSO flagged for exclusion (e.g. "post only
        # electronics, no fashion") stays excluded — deny wins over a broad include.
        named_m = [m for m in avail_m if _mentions(t, m) and m not in excl_m]
        if named_m:
            out["merchants"] = set(named_m)
        named_c = [c for c in avail_c if _mentions(t, c) and c not in excl_c]
        if named_c:
            out["categories"] = set(named_c)
    out["exclude_merchants"] = excl_m or None
    out["exclude_categories"] = excl_c or None
    out["after_min"], out["before_min"] = _parse_time_window(t)
    out["price_min"], out["price_max"] = _parse_price_window(t)
    return out


# ── Universal steer: AI-interpret ANY free-text into a structured, validated intent ──

_STEER_INTENT_SYSTEM = (
    "You convert a deals-channel operator's free-text steering instruction into a STRICT "
    "JSON intent that a deterministic engine then ENFORCES. You are given the ONLY merchants "
    "and categories in today's live feed — every merchant/category you output MUST be copied "
    "EXACTLY (same spelling) from those lists; NEVER invent one. Extract only what the "
    "operator actually asked; leave everything else null/empty.\n"
    "Output EXACTLY this JSON object and nothing else:\n"
    "{\n"
    '  "target_posts": <int|null>,             // desired POST COUNT. For a correction like\n'
    '                                           //   "not 39, make it 10" use the NEW value (10).\n'
    '  "target_posts_period": "day"|"week"|null,  // ONLY set "week" when the operator says the\n'
    '                                              // number is a TOTAL for the whole week ("40\n'
    '                                              // posts this week", "60 for the week") — NOT\n'
    '                                              // when the number is per-day (default "day" for\n'
    '                                              // a bare count like "post 20", "make it 10").\n'
    '  "target_posts_mode": "total"|"additional"|null,  // "additional" ONLY when the operator\n'
    '                                                    // clearly wants N NEW posts on top of\n'
    '                                                    // whatever already went out today — cues\n'
    '                                                    // like "from now", "more", "additional",\n'
    '                                                    // "extra" ("20 posts from now", "5 more\n'
    '                                                    // posts"). Default "total" (or null) for a\n'
    '                                                    // bare count ("post 20 today") — that means\n'
    '                                                    // 20 for the WHOLE day, already-posted ones\n'
    '                                                    // included, NOT 20 additional.\n'
    '  "merchants_only": [<feed merchant slugs>],    // restrict to ONLY these merchants\n'
    '  "merchants_exclude": [<feed merchant slugs>], // avoid these merchants\n'
    '  "categories_only": [<feed category slugs>],\n'
    '  "categories_exclude": [<feed category slugs>],\n'
    '  "price_min": <int|null>, "price_max": <int|null>,   // rupees\n'
    '  "after_time": "HH:MM"|null,   // earliest a post may fire (24h IST)\n'
    '  "before_time": "HH:MM"|null,  // latest a post may fire\n'
    '  "type_lean": "single"|"loot"|null,   // lean the single/loot mix\n'
    '  "pause": <bool>,              // true ONLY to STOP/pause posting entirely\n'
    '  "interpretation": "<ONE plain sentence of what you understood>",\n'
    '  "unsupported": ["<any ask that maps to NO field above, with a short why>"]\n'
    "}\n"
    "Rules: only set merchants_only/categories_only when the operator clearly wants ONLY "
    "those for the WHOLE remaining day; a bare mention ('push electronics') is a soft lean, "
    "not a hard filter — put a soft lean in interpretation, not in the *_only fields. This "
    "still applies when a TIME is attached: 'post amazon at 9' / 'include an amazon post "
    "this morning' / 'want to post amazon today morning 9' asks for ONE (or a few) extra "
    "amazon post around that time, NOT amazon for every remaining slot — leave "
    "merchants_only EMPTY and describe the single addition in interpretation instead (set "
    "after_time only if a real time window was given). Only set merchants_only when the "
    "operator says something like 'only amazon', 'just flipkart', 'nothing but ajio', or "
    "'stick to X' — words that exclude every other merchant for the rest of the day. "
    "'pause' is ONLY for stopping posting, NEVER for 'don't post <category>' (that is "
    "categories_exclude). Caption tone/wording, conversion/sales/CTR, or anything with no "
    "field above goes in 'unsupported'.")


def _hhmm_to_min(s) -> int | None:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", s or "") if isinstance(s, str) else None
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return min(h, 24) * 60 + mi if 0 <= h <= 24 and 0 <= mi < 60 else None


# A weekly-TOTAL cue ("this week", "for the week", "a week", "/week") beats a per-day
# reading — used only when the AI intent call is unavailable (extract_steer_intent's
# regex fallback); the AI path gets this distinction directly via target_posts_period.
_PER_WEEK_CUE_RE = re.compile(r"\b(?:this week|for the week|a week|per week|/\s*week|weekly total)\b")

# An "additional, not total" cue ("from now", "more", "additional", "extra") — the same
# regex-fallback role as _PER_WEEK_CUE_RE, for when the AI intent call is unavailable.
# "20 posts from now" / "5 more posts" / "make it 20 more" means N NEW ones on top of
# what's already posted today, NOT N as the whole day's total (the default bare-count
# reading). Only consulted alongside an already-detected target_posts number, so a loose
# "more"/"extra" match is low-risk — it can't fire without a real count present too.
_ADDITIONAL_CUE_RE = re.compile(r"\b(?:from now|more|additional|extra)\b")


def _regex_intent(directive: str | None, available_merchants, available_categories) -> dict:
    """Deterministic fallback intent from the regex parsers — used when the AI intent call
    fails, so steering never breaks. Same shape as ``extract_steer_intent``."""
    cons = parse_directive_constraints(directive, available_merchants, available_categories)
    tp = parse_target_posts(directive)
    unsupported = []
    # parse_target_posts silently drops a raw candidate outside 1..350 — recover it here
    # (same regex, no clamp) so an ask like "400 posts this week" is surfaced as an
    # honestly-unsupported count instead of vanishing with no trace. Same reasoning as
    # extract_steer_intent's AI-path clamp note.
    if tp is None and directive:
        _raw = [int(g1 or g2) for g1, g2 in _TARGET_POSTS_RE.findall(directive.lower())]
        _oor = [n for n in _raw if not (1 <= n <= 350)]
        if _oor:
            unsupported.append(f"{_oor[-1]} posts is outside the supported 1-350 range, "
                               "so the count wasn't changed")
    return {**cons,
            "target_posts": tp,
            "target_posts_period": ("week" if tp is not None and directive
                                    and _PER_WEEK_CUE_RE.search(directive.lower()) else None),
            "target_posts_mode": ("additional" if tp is not None and directive
                                  and _ADDITIONAL_CUE_RE.search(directive.lower()) else None),
            "pause": parse_pause(directive),
            "type_lean": None,
            "interpretation": "", "unsupported": unsupported, "source": "regex"}


def extract_steer_intent(directive: str | None,
                         available_merchants: list[str] | None = None,
                         available_categories: list[str] | None = None,
                         *, provider: str = "groq") -> dict:
    """AI-interpret ANY free-text steer into a validated, structured intent — the universal
    replacement for the regex parsers, so any phrasing / compound ask works. Merchants and
    categories are validated against the REAL feed (invalid ones dropped, never invented);
    count is clamped; times/prices sanitised. On AI failure or an unparseable reply it FALLS
    BACK to the regex parsers so steering never breaks.

    Returns the dict the existing enforcers consume — merchants / categories /
    exclude_merchants / exclude_categories / after_min / before_min / price_min / price_max
    — PLUS target_posts, pause, type_lean, interpretation, unsupported, source."""
    if not directive or not directive.strip():
        return {"merchants": None, "categories": None, "exclude_merchants": None,
                "exclude_categories": None, "after_min": None, "before_min": None,
                "price_min": None, "price_max": None, "target_posts": None,
                "target_posts_period": None, "target_posts_mode": None, "pause": False,
                "type_lean": None, "interpretation": "", "unsupported": [], "source": "empty"}

    from src.ai.client import AIClient, AIUnavailable
    from src.ai.planner import _extract_json_object, _loads_lenient

    avail_m = {m.lower(): m for m in (available_merchants or [])}
    avail_c = {c.lower(): c for c in (available_categories or [])}
    user = ("MERCHANTS (feed): " + (", ".join(sorted(avail_m.values())) or "none") + "\n"
            "CATEGORIES (feed): " + (", ".join(sorted(avail_c.values())) or "none") + "\n\n"
            "OPERATOR STEER:\n" + directive)
    try:
        raw = AIClient().complete(user, system_extra=_STEER_INTENT_SYSTEM, max_tokens=600,
                                  trace_call="steer_intent", provider=provider)
        obj = _extract_json_object(raw)
        parsed = _loads_lenient(obj) if obj else None
        if not isinstance(parsed, dict):
            raise ValueError("no JSON intent")
    except (AIUnavailable, ValueError, Exception):
        return _regex_intent(directive, available_merchants, available_categories)

    def _valid(lst, pool):  # keep only real feed slugs (case-insensitive), exact spelling
        out = {pool[x.lower()] for x in (lst or []) if isinstance(x, str) and x.lower() in pool}
        return out or None

    tp = parsed.get("target_posts")
    try:
        tp = int(tp) if tp is not None else None
    except (TypeError, ValueError):
        tp = None
    # A count outside the supported range is DROPPED, not silently ignored — without a
    # trace here, the deterministic count stays unchanged (e.g. "300 posts this week"
    # fails this clamp -> target_posts=None -> posts_per_day never moves) while the AI's
    # own free-text narrative still parrots "300" because it saw the raw directive text,
    # producing a real contradiction between the prose and the actual numbers. Surfacing
    # it in `unsupported` lets the caller tell the operator plainly instead.
    tp_out_of_range_note = None
    if tp is not None and not (1 <= tp <= 350):
        tp_out_of_range_note = f"{tp} posts is outside the supported 1-350 range, so the count wasn't changed"
        tp = None
    pmin, pmax = parsed.get("price_min"), parsed.get("price_max")
    pmin = int(pmin) if isinstance(pmin, (int, float)) else None
    pmax = int(pmax) if isinstance(pmax, (int, float)) else None
    if pmin is not None and pmax is not None and pmin > pmax:
        pmin, pmax = pmax, pmin
    lean = parsed.get("type_lean")
    lean = lean if lean in ("single", "loot") else None
    tp_period = parsed.get("target_posts_period")
    tp_period = tp_period if tp_period in ("day", "week") else None
    tp_mode = parsed.get("target_posts_mode")
    tp_mode = tp_mode if tp_mode in ("total", "additional") else None
    unsupported = [u for u in (parsed.get("unsupported") or []) if isinstance(u, str) and u.strip()]
    if tp_out_of_range_note:
        unsupported.append(tp_out_of_range_note)
    return {
        "merchants": _valid(parsed.get("merchants_only"), avail_m),
        "exclude_merchants": _valid(parsed.get("merchants_exclude"), avail_m),
        "categories": _valid(parsed.get("categories_only"), avail_c),
        "exclude_categories": _valid(parsed.get("categories_exclude"), avail_c),
        "after_min": _hhmm_to_min(parsed.get("after_time")),
        "before_min": _hhmm_to_min(parsed.get("before_time")),
        "price_min": pmin, "price_max": pmax,
        "target_posts": tp, "target_posts_period": tp_period, "target_posts_mode": tp_mode,
        "pause": bool(parsed.get("pause")),
        "type_lean": lean,
        "interpretation": (parsed.get("interpretation") or "").strip(),
        "unsupported": unsupported, "source": "ai",
    }


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
    excl_m = constraints.get("exclude_merchants")
    excl_c = constraints.get("exclude_categories")
    if not allowed_m and not allowed_c and not excl_m and not excl_c:
        return []

    def _describe() -> str:
        want = []
        if allowed_m:
            want.append("merchants " + "/".join(sorted(allowed_m)))
        if allowed_c:
            want.append("categories " + "/".join(sorted(allowed_c)))
        if excl_m:
            want.append("excluding merchant(s) " + "/".join(sorted(excl_m)))
        if excl_c:
            want.append("excluding categor(y/ies) " + "/".join(sorted(excl_c)))
        return "; ".join(want)

    pairs = feed_pairs or {}
    valid = [(m, c) for (m, c) in pairs
             if (not allowed_m or m in allowed_m) and (not allowed_c or c in allowed_c)
             and (not excl_m or m not in excl_m) and (not excl_c or c not in excl_c)]
    if not valid:
        return [f"today's feed has no deals matching your steer ({_describe()}), "
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
        return [f"{changed} slot(s) reassigned to honor your steer ({_describe()})"]
    return []


def apply_price_constraints(slots: list[dict], constraints: dict) -> list[str]:
    """Set the operator's rupee bounds on LOOT (collection) slots, IN PLACE — jit_fill
    fetches items within max_price/min_price for a price-tier loot. Single slots are left
    untouched (a single is one specific deal, not a price-filtered board). Returns an
    honest note when applied, and one caveat when the steer's price only fits loots but
    the day has none."""
    from src.services.generation.constants import is_loot_type

    lo, hi = constraints.get("price_min"), constraints.get("price_max")
    if lo is None and hi is None:
        return []
    loot = [sl for sl in slots if is_loot_type(sl.get("type"))]
    for sl in loot:
        if hi is not None:
            sl["max_price"] = hi
        if lo is not None:
            sl["min_price"] = lo
    band = (f"₹{lo}-₹{hi}" if lo is not None and hi is not None
            else f"under ₹{hi}" if hi is not None else f"over ₹{lo}")
    if not loot:
        return [f"your price steer ({band}) applies to loot boards, but today's plan has "
                "no loot slots — singles are single specific deals, not price-filtered, "
                "so nothing was capped"]
    return [f"{len(loot)} loot slot(s) capped to {band} per your steer"]


def enforce_weekly_constraints(blueprint: dict, intent: dict) -> list[str]:
    """Apply a validated steer intent to the WEEKLY blueprint's direction-level knobs, IN
    PLACE. The week has no per-post slots (those only exist in the daily plan), so only
    what's genuinely weekly-scoped can be steered: which merchants this week prioritizes,
    the loot/single lean, and the posts/day target the daily plans read as THIS_WEEK
    direction. Returns honest notes — what changed, and what a weekly steer can't reach
    (price/time/category are per-slot and have no weekly analogue) — so the operator is
    never told a steer applied when it silently didn't."""
    notes: list[str] = []
    allowed_m, excl_m = intent.get("merchants"), intent.get("exclude_merchants")
    priorities = blueprint.get("merchant_priorities") or []

    def _name(p):
        return p.get("merchant") if isinstance(p, dict) else p

    if allowed_m or excl_m:
        kept = [p for p in priorities
                if (not allowed_m or _name(p) in allowed_m)
                and (not excl_m or _name(p) not in excl_m)]
        if kept or excl_m:
            blueprint["merchant_priorities"] = kept
        if allowed_m and kept:
            notes.append(f"merchant priorities narrowed to {'/'.join(sorted(allowed_m))} per your steer")
        elif allowed_m:
            notes.append(f"none of your requested merchants ({'/'.join(sorted(allowed_m))}) were in "
                         "this week's merchant priorities, so the list was left unchanged")
        if excl_m:
            notes.append(f"{'/'.join(sorted(excl_m))} dropped from this week's merchant priorities per your steer")

    lean = intent.get("type_lean")
    if lean in ("single", "loot"):
        # Same 30–70 band the deterministic weekly split clamps to (_weekly_ai_generate) —
        # a lean is a nudge within that band, never a hard 100/0 override.
        loot_pct = 65 if lean == "loot" else 35
        blueprint["loot_deal_ratio"] = {"loot": loot_pct, "deal": 100 - loot_pct}
        for t in (blueprint.get("daily_themes") or []):
            if isinstance(t, dict):
                t["loot_share"], t["single_share"] = round(loot_pct / 100, 3), round((100 - loot_pct) / 100, 3)
        notes.append(f"leaned this week's mix toward {'loot boards' if lean == 'loot' else 'single deals'} per your steer")

    target = intent.get("target_posts")
    if target:
        # A bare count ("post 20", "make it 10") defaults to the per-day cadence —
        # the same figure daily_brief's recommended_posts steers to. But when the
        # operator explicitly frames it as a WEEKLY total ("40 posts this week"),
        # target_posts_period says "week" and the per-day figure must be derived
        # (40/week != 40/day, which would silently 7x the real ask to 280/week).
        if intent.get("target_posts_period") == "week":
            per_day = max(1, round(target / 7))
            blueprint["posts_per_day"], blueprint["posts_per_week"] = per_day, target
            notes.append(f"posts/week set to {target} (~{per_day}/day) per your steer")
        else:
            blueprint["posts_per_day"], blueprint["posts_per_week"] = target, target * 7
            notes.append(f"posts/day set to {target} per your steer")
        for t in (blueprint.get("daily_themes") or []):
            if isinstance(t, dict):
                t["posts_planned"] = blueprint["posts_per_day"]

    if intent.get("price_min") is not None or intent.get("price_max") is not None:
        notes.append("price bands apply per-slot, which only exist in the daily plan — steer a specific day for that")
    if intent.get("after_min") is not None or intent.get("before_min") is not None:
        notes.append("timing windows apply per-slot, which only exist in the daily plan — steer a specific day for that")
    if intent.get("categories") or intent.get("exclude_categories"):
        notes.append("category steers apply per-slot, which only exist in the daily plan — steer a specific day for that")
    return notes


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
    # EXCLUSION steers: "avoid ajio" denies ajio (no restrict cue needed).
    ex = parse_directive_constraints("avoid ajio today", merch, cats)
    assert ex["exclude_merchants"] == {"ajio"} and ex["merchants"] is None, ex
    # mixed: include electronics but exclude fashion in one directive.
    mix = parse_directive_constraints("post only electronics deals, no fashion", merch, cats)
    assert mix["categories"] == {"electronics-and-gadgets"}, mix
    assert mix["exclude_categories"] == {"fashion-and-lifestyle"}, mix
    # enforcement honors the deny-list: an ajio slot must move OFF ajio.
    ex_slots = [{"merchant": "ajio", "theme": "fashion-and-lifestyle", "why": "x"},
                {"merchant": "amazon", "theme": "electronics-and-gadgets", "why": "x"}]
    note = enforce_pair_constraints(ex_slots, {"exclude_merchants": {"ajio"}}, feed)
    assert all(sl["merchant"] != "ajio" for sl in ex_slots), ex_slots
    assert note and "excluding" in note[0], note

    # ALIAS/typo canonicalization: 'amzn' and a misspelling both resolve to feed slugs.
    assert parse_directive_constraints("focus on amzn only", merch, cats)["merchants"] == {"amazon"}
    assert parse_directive_constraints("avoid flipkrt", merch, cats)["exclude_merchants"] == {"flipkart"}

    # PRICE steers: under / over / band; clock spans are NOT misread as prices.
    assert _parse_price_window("only deals under ₹1000") == (None, 1000)
    assert _parse_price_window("nothing over rs 500") == (500, None)
    assert _parse_price_window("show ₹500-₹1500 loots") == (500, 1500)
    assert _parse_price_window("post only in the evening 18:00-21:00") == (None, None)
    # contradictory bounds normalize to a sane band (min<=max), never an impossible range.
    assert _parse_price_window("over 1500 under 500") == (500, 1500)
    # price applies to loot slots only; singles untouched.
    pslots = [{"type": "collection", "max_price": None, "min_price": None},
              {"type": "single", "max_price": None, "min_price": None}]
    pnote = apply_price_constraints(pslots := pslots, {"price_min": None, "price_max": 999})
    assert pslots[0]["max_price"] == 999 and pslots[1]["max_price"] is None, pslots
    assert pnote and "999" in pnote[0], pnote

    # PAUSE intents recognized; a content exclusion is NOT a pause.
    assert parse_pause("pause posting") and parse_pause("don't post today")
    assert parse_pause("stop") and parse_pause("no posts today")
    assert not parse_pause("don't post electronics")   # exclusion, not a pause
    assert not parse_pause("focus on amazon")

    # QUANTITY steers: explicit count parsed; a plain lean has none.
    assert parse_target_posts("post 20 today") == 20
    assert parse_target_posts("30 posts please") == 30
    assert parse_target_posts("push electronics harder") is None
    # a bare number without a post-verb/noun is ignored (avoids matching '6pm' etc.)
    assert parse_target_posts("focus after 6pm") is None
    # a CORRECTION drops the rejected number and takes the target (not the first number).
    assert parse_target_posts("i don't want 39 posts, make it 30, on the new 30 posts") == 30
    assert parse_target_posts("reduce to 15") == 15
    assert parse_target_posts("not 40 — set to 25") == 25

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