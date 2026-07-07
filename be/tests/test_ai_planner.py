from __future__ import annotations
import pytest
from src.ai.planner import parse_plan


def test_parse_plan_extracts_json_block():
    raw = (
        "Here is the plan:\n"
        '{"date":"2026-07-08","post_slots":[{"type":"single","window_ist":"12:00-13:00","theme":"electronics","why":"x"}],'
        '"emphasis":"push electronics","watch":"forwards down","cited_numbers":[2100,980,0.3]}\n'
        "Hope this helps!"
    )
    plan = parse_plan(raw)
    assert plan["date"] == "2026-07-08"
    assert plan["post_slots"][0]["theme"] == "electronics"
    assert plan["cited_numbers"] == [2100, 980, 0.3]


def test_parse_plan_raises_on_garbage():
    with pytest.raises(ValueError):
        parse_plan("no json here at all")
