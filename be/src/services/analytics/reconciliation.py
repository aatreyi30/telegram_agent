"""Closed-loop feedback (rescue plan §3.5).
adherence  = deterministic: planned slots vs actually-published posts (FACT).
attribution = correlational: expected_outcome vs actual report (NOT causal)."""
from __future__ import annotations


def _hour_of(window_ist: str) -> int | None:
    try:
        return int(window_ist.split(":")[0])
    except (ValueError, AttributeError, IndexError):
        return None


def compute_adherence(plan_slots: list[dict], published: list[dict]) -> dict:
    planned = len(plan_slots or [])
    pub = list(published or [])
    pub_hours = [p.get("hour_ist") for p in pub]
    matched = 0
    missed_windows: list[str] = []
    remaining = list(pub_hours)
    for slot in plan_slots or []:
        h = _hour_of(slot.get("window_ist", ""))
        # a slot is matched if a post published within +/-1h of its window start
        hit = next((ph for ph in remaining if ph is not None and h is not None and abs(ph - h) <= 1), None)
        if hit is not None:
            matched += 1
            remaining.remove(hit)
        else:
            missed_windows.append(slot.get("window_ist", "?"))

    def _bytype(items, key):
        out: dict[str, int] = {}
        for it in items:
            t = it.get("type", "?")
            out[t] = out.get(t, 0) + 1
        return out

    return {
        "planned": planned,
        "published": len(pub),
        "matched": matched,
        "missed_windows": missed_windows,
        "by_type": {"planned": _bytype(plan_slots or [], "type"), "published": _bytype(pub, "type")},
    }
