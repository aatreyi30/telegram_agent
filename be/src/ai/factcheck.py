"""Deterministic guard: every number the AI cited must appear in the report
rows it was given. Closes the prompt-only 'no hallucinated numbers' gap."""
from __future__ import annotations

import re

# Every "23" or "474.8" or "1,234" in a piece of free text (comma thousands-
# separators optionally present, decimal part optional).
_NUM_RE = re.compile(r"\d[\d,]*\.?\d*")
# The hour(s) inside a "HH:MM-HH:MM" window string, e.g. "06:00-11:00" -> 6, 11.
_WINDOW_HOUR_RE = re.compile(r"(\d{1,2}):\d{2}")
# HH and MM of a single "HH:MM" instant (the per-post `time_ist` shape), e.g.
# "09:05" -> (9, 5) — both parts, since a `why` restating the exact minute
# ("posting at 09:05") must also be self-valid.
_TIME_IST_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


# Terms that imply an outcome we do NOT measure. Telegram gives views / reactions /
# forwards only; there is no click, conversion, CTR, or revenue data anywhere
# (`affiliate_links` carries none). Any such claim in the plan prose is ungrounded
# by construction, and the number-only fact-check can't catch it (no figure to
# verify). Word-boundary, case-insensitive; kept tight to unambiguous metric words
# so festival "sale"/"order"/"purchase" reasoning isn't false-flagged.
_UNMEASURABLE_RE = re.compile(
    r"\b(conversions?|convert(?:s|ing|ed)?|click[\s-]?throughs?|clickthroughs?|ctr|"
    r"revenue|roas|roi)\b",
    re.IGNORECASE,
)


def unmeasurable_claims(plan: dict) -> list[str]:
    """Distinct terms in the plan's prose that assert an outcome we don't track
    (conversion / click-through / CTR / revenue / ROI / ROAS). Empty when clean.
    Used to downgrade a plan's factcheck status to 'warn' — the guard the
    number-only ``check_cited_numbers`` cannot provide, since these claims carry no
    verifiable number (see the '22:00 fashion conversion rates' hallucination)."""
    texts = [plan.get("digest"), plan.get("cadence_why"), plan.get("emphasis"),
             plan.get("watch"), plan.get("direction")]
    for sl in plan.get("post_slots") or []:
        texts.append(sl.get("why"))
    for t in plan.get("daily_themes") or []:
        texts.append(t.get("why"))
    seen: set[str] = set()
    out: list[str] = []
    for t in texts:
        if not isinstance(t, str):
            continue
        for m in _UNMEASURABLE_RE.finditer(t):
            term = m.group(0).lower()
            key = term.replace(" ", "").replace("-", "")
            if key not in seen:
                seen.add(key)
                out.append(term)
    return out


# A line-leading enumeration marker ("1. ", "2) ") — the digest's numbered plan points.
# These are list ordinals, not cited data, so they must NOT be fact-checked as claims
# (else "1."/"2." read as unverified numbers and can fail an otherwise-grounded plan).
_LIST_MARKER_RE = re.compile(r"(?m)^\s*\d+[.)]\s+")


def _numbers_in(text) -> list[float]:
    if not text or not isinstance(text, str):
        return []
    text = _LIST_MARKER_RE.sub("", text)
    out = []
    for m in _NUM_RE.findall(text):
        cleaned = m.replace(",", "").strip(".")
        if not cleaned:
            continue
        try:
            out.append(float(cleaned))
        except ValueError:
            continue
    return out


def extract_prose_numbers(plan: dict) -> list[float]:
    """Numbers in the plan's free-text (digest/why/etc.) — the real fact-check
    surface, since the model leaves its self-declared ``cited_numbers`` empty.
    Caller merges ``digest`` into the parsed plan first (parse_plan drops it)."""
    texts = [plan.get("digest"), plan.get("cadence_why"), plan.get("emphasis"),
             plan.get("watch"), plan.get("direction")]
    for sl in plan.get("post_slots") or []:
        texts.append(sl.get("why"))
    for t in plan.get("daily_themes") or []:
        texts.append(t.get("why"))
        texts.append(t.get("theme") or t.get("theme_focus"))
    nums: list[float] = []
    for t in texts:
        nums.extend(_numbers_in(t))
    return nums


def plan_structural_numbers(plan: dict) -> list[float]:
    """The plan's OWN decision numbers (slot counts/windows/prices, recommended_posts,
    date, loot ratio, per-day shares). Self-valid — the model chose them, didn't
    measure them — so restating them in prose must never count as a fabrication."""
    nums: list[float] = []
    for sl in plan.get("post_slots") or []:
        for key in ("count", "max_price", "min_price"):
            v = sl.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                nums.append(float(v))
        nums.extend(float(h) for h in _WINDOW_HOUR_RE.findall(sl.get("window_ist") or ""))
        # S2-a: `time_ist` (the new per-post shape, e.g. "09:05") replaced
        # `window_ist`'s HH:MM-HH:MM span, but was never added to the
        # structural whitelist. The prompt now requires each `why` to justify
        # its own scheduled time, so "posting at 09:05" restates the slot's
        # OWN hour AND minute — both must be self-valid, same as window_ist's
        # hour already is, or a plan can be marked `failed` for citing its own
        # schedule.
        tm = _TIME_IST_RE.match(sl.get("time_ist") or "")
        if tm:
            nums.append(float(tm.group(1)))
            nums.append(float(tm.group(2)))
    rec = plan.get("recommended_posts")
    if isinstance(rec, (int, float)) and not isinstance(rec, bool):
        nums.append(float(rec))
    for part in re.split(r"\D+", plan.get("date") or ""):
        if part:
            nums.append(float(part))
    ratio = plan.get("loot_deal_ratio") or {}
    for v in ratio.values():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            nums.append(float(v))
    for t in plan.get("daily_themes") or []:
        for key in ("posts_planned", "loot_share", "single_share"):
            v = t.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                nums.append(float(v))
    return nums


def _numeric_values(reports: list[dict]) -> list[float]:
    vals: list[float] = []
    for r in reports:
        for v in r.values():
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                vals.append(float(v))
            elif isinstance(v, dict):
                vals.extend(float(x) for x in v.values() if isinstance(x, (int, float)) and not isinstance(x, bool))
    return vals


def _matches(target: float, pool: list[float], tolerance: float) -> bool:
    for v in pool:
        if target == v:
            return True
        denom = abs(v) if v else 1.0
        if abs(target - v) / denom <= tolerance:
            return True
    return False


def check_cited_numbers(cited: list[float], reports: list[dict], *, tolerance: float = 0.02,
                        warn_ratio: float = 0.25) -> dict:
    """Graduated trust, not all-or-nothing:

      * ``passed``  — every cited number is grounded in the data pool.
      * ``warn``    — a small MINORITY (<= ``warn_ratio``) is unverified. This is
                      almost always a non-metric token the model swept into
                      ``cited_numbers`` (a clock hour like "23" from "21-23", a
                      derived ratio, a differently-rounded figure). Cited numbers
                      only appear in the plan's rationale text, never in the
                      published post, so a mostly-grounded plan is safe to act on.
      * ``failed``  — a substantial fraction is unverified => likely fabrication;
                      the plan is not trusted and downstream filling is refused.
    """
    pool = _numeric_values(reports)
    nums = [float(c) for c in (cited or []) if isinstance(c, (int, float)) and not isinstance(c, bool)]
    unverified = [c for c in nums if not _matches(c, pool, tolerance)]
    if not unverified:
        status = "passed"
    elif len(unverified) / max(len(nums), 1) <= warn_ratio:
        status = "warn"
    else:
        status = "failed"
    return {"status": status, "unverified": unverified}


def _demo() -> None:
    """Runnable self-check (no DB): prose-number extraction picks up fabricated
    figures the model never declared in ``cited_numbers``, and structural numbers
    (the plan's own count/window/date/ratio fields) never get flagged."""
    daily = {
        "digest": "Yesterday hit 474.8 views.", "cadence_why": "test", "emphasis": "e",
        "watch": "w", "date": "2026-07-08", "recommended_posts": 6,
        "post_slots": [{"count": 6, "window_ist": "06:00-11:00", "max_price": 999,
                        "why": "expect 250 views here"}],
    }
    prose = extract_prose_numbers(daily)
    assert 474.8 in prose and 250.0 in prose, prose
    structural = plan_structural_numbers(daily)
    assert set(structural) >= {6.0, 11.0, 999.0, 2026.0, 7.0, 8.0}, structural
    # the structural numbers must never show up as unverified prose claims
    fc = check_cited_numbers(prose, [{"s": v} for v in structural])
    assert fc["status"] == "failed", fc  # 474.8/250 are real fabrications, unrelated to structural

    weekly = {"digest": "d", "direction": "lean loot 60%", "daily_themes": [
        {"why": "amazon drove 33.3 views/day", "posts_planned": 5, "loot_share": 0.6,
         "single_share": 0.4}]}
    wprose = extract_prose_numbers(weekly)
    assert 60.0 in wprose and 33.3 in wprose, wprose
    wstruct = plan_structural_numbers(weekly)
    assert set(wstruct) >= {5.0, 0.6, 0.4}, wstruct

    # unmeasurable-claim guard: flags outcomes we don't track, ignores clean prose
    bad = unmeasurable_claims({"post_slots": [
        {"why": "fashion has good conversion rates late evening"},
        {"why": "great CTR and revenue potential here"}]})
    assert set(bad) == {"conversion", "ctr", "revenue"}, bad
    assert unmeasurable_claims({"digest": "amazon drew 400 views; post loot at 8pm",
                                "post_slots": [{"why": "high views, order early"}]}) == []

    # numbered plan-point markers ("1.", "2.") are ordinals, not cited data — they must
    # NOT appear as prose numbers (the real cited figure on the line still does).
    numbered_digest = {"digest": "Yesterday: hit 233 views/post.\n"
                       "1. Push Amazon (48 views/day).\n2. Add loot in the evening."}
    pn = extract_prose_numbers(numbered_digest)
    assert 1.0 not in pn and 2.0 not in pn, pn
    assert 233.0 in pn and 48.0 in pn, pn

    print("ai/factcheck.py self-check OK")


if __name__ == "__main__":
    _demo()
