"""Deterministic guard: every number the AI cited must appear in the report
rows it was given. Closes the prompt-only 'no hallucinated numbers' gap."""
from __future__ import annotations


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


def check_cited_numbers(cited: list[float], reports: list[dict], *, tolerance: float = 0.02) -> dict:
    pool = _numeric_values(reports)
    unverified = [c for c in (cited or []) if isinstance(c, (int, float)) and not _matches(float(c), pool, tolerance)]
    return {"status": "failed" if unverified else "passed", "unverified": unverified}
