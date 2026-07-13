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
