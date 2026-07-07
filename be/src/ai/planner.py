"""AI analyst + planner. Reads DailyChannelReport rows, emits a grounded digest
+ structured day plan. AIClient has no JSON mode, so we prompt for JSON and
parse defensively; numbers are fact-checked downstream (ai/factcheck.py)."""
from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from src.ai.client import AIClient, AIUnavailable
from src.ai.context import planning_context, to_json

PLAN_SCHEMA_KEYS = ("date", "post_slots", "emphasis", "watch", "cited_numbers")

_PLAN_INSTRUCTIONS = (
    "You are the channel's daily analyst and planner. You are given recent daily "
    "report rows (facts) and a trailing baseline. Do two things:\n"
    "1) Write a 3-4 sentence DIGEST: how yesterday went vs baseline, and today's focus.\n"
    "2) Produce a DAY PLAN as JSON.\n\n"
    "HARD RULES:\n"
    "- Use ONLY numbers that appear in the DATA. Never invent a number.\n"
    "- Put every number you cite into cited_numbers.\n"
    "- Do not invent deals, prices, links, or merchants.\n\n"
    "Output EXACTLY:\n"
    "First the digest paragraph, then on a new line the token ===PLAN=== , then a JSON object:\n"
    '{"date":"YYYY-MM-DD","post_slots":[{"type":"single|collection","window_ist":"HH:MM-HH:MM",'
    '"theme":"<category>","why":"<short>"}],"emphasis":"<one line>","watch":"<one line>",'
    '"cited_numbers":[<numbers you used>]}'
)


def parse_plan(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("no JSON object found in model output")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"plan JSON invalid: {e}") from e
    data.setdefault("post_slots", [])
    data.setdefault("cited_numbers", [])
    if not isinstance(data.get("post_slots"), list):
        raise ValueError("post_slots must be a list")
    return data


def _split_digest_and_plan(raw: str) -> tuple[str, str]:
    if "===PLAN===" in raw:
        digest, _, plan = raw.partition("===PLAN===")
        return digest.strip(), plan.strip()
    # fallback: digest is everything before the first '{'
    idx = raw.find("{")
    return (raw[:idx].strip() if idx > 0 else ""), raw[idx:] if idx >= 0 else raw


def generate_day_plan(s: Session) -> dict:
    ctx = planning_context(s)
    if not ctx.get("reports"):
        return {"available": False, "reason": "no report rows yet", "plan": None, "digest": ""}
    report_ids = [r["id"] for r in ctx["reports"] if r.get("id") is not None]
    ai = AIClient()
    try:
        user = f"{_PLAN_INSTRUCTIONS}\n\nDATA:\n{to_json(ctx)}"
        raw = ai.complete(user, max_tokens=1500)
    except AIUnavailable as e:
        return {"available": False, "reason": str(e), "plan": None, "digest": ""}
    digest, plan_text = _split_digest_and_plan(raw)
    try:
        plan = parse_plan(plan_text)
    except ValueError:
        return {"available": False, "reason": "unparseable plan", "plan": None, "digest": digest}
    return {"available": True, "digest": digest, "plan": plan, "report_ids": report_ids}
