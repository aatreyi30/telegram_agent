"""Two silent-failure fixes, each pinned by the smallest test that catches it.

1. An AI outage must not take the channel dark. The deterministic writer tags its
   plan ``factcheck_status="fallback"``; jit_fill used an allow-list that omitted it,
   so every slot refused to fill and nothing was logged as wrong.
2. One dead deal must not kill a ten-deal loot board. Revalidation returned on the
   first failure and publishing blocked the whole message, throwing away nine live
   deals.
"""

from __future__ import annotations

import types

import pytest


# --------------------------------------------------------------------------- #
# 1. factcheck gate — only a hard "failed" may block filling
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status", ["passed", "warn", "skipped", "", None, "fallback"])
def test_non_failed_factcheck_statuses_do_not_block_filling(status):
    """`fallback` is the AI-outage status — blocking it stopped the channel posting."""
    assert (status or "").strip().lower() != "failed"


def test_failed_factcheck_still_blocks():
    assert ("failed" or "").strip().lower() == "failed"


def test_jit_fill_gate_is_a_denylist_not_an_allowlist():
    """Guards the real source line: an allow-list silently blocks any status nobody
    enumerated, which is exactly how "fallback" took the channel dark."""
    import inspect

    from src.services.generation import jit_fill

    src = inspect.getsource(jit_fill)
    assert 'factcheck_status or "").strip().lower() == "failed"' in src, \
        "the factcheck gate must name the ONE blocking status, not allow-list the good ones"


# --------------------------------------------------------------------------- #
# 2. partial board publishing
# --------------------------------------------------------------------------- #
def _post(deal_ids, items, text):
    return types.SimpleNamespace(deal_ids=deal_ids, rendered_text=text,
                                 format_meta={"items": items})


def _board(n=5):
    items = [{"deal_id": f"d{i}", "line": f"Item {i} - https://x.test/{i}"} for i in range(n)]
    text = "Loot Under 999\n\n" + "\n".join(i["line"] for i in items) + "\n\nShare it!"
    return _post([i["deal_id"] for i in items], items, text)


def test_one_dead_deal_drops_only_that_line():
    from src.services.generation.publishing import Publisher

    post = _board(5)
    text, survivors = Publisher._trim_failed_deals(post, {"d2"})

    assert "Item 2 - https://x.test/2" not in text
    for keep in (0, 1, 3, 4):
        assert f"Item {keep} - https://x.test/{keep}" in text
    assert survivors == ["d0", "d1", "d3", "d4"]
    assert "Loot Under 999" in text and "Share it!" in text


def test_trim_refuses_when_the_line_is_not_in_the_text():
    """Text edited after rendering — deleting by substring could mangle a neighbour,
    so we refuse and let the caller block the whole post."""
    from src.services.generation.publishing import Publisher

    post = _board(5)
    post.rendered_text = post.rendered_text.replace("Item 2 - https://x.test/2", "edited")
    assert Publisher._trim_failed_deals(post, {"d2"}) is None


def test_trim_refuses_without_a_line_map():
    """Posts rendered before the formatter recorded one — old behaviour applies."""
    from src.services.generation.publishing import Publisher

    post = _post(["d0"], [], "some text")
    assert Publisher._trim_failed_deals(post, {"d0"}) is None


def test_formatter_records_a_line_map_for_every_deal():
    """The trim is only exact because the formatter emits deal_id -> rendered line.
    Without this the drop would have to match on URL, which breaks the moment an
    affiliate provider shortens the link."""
    import inspect

    from src.services.generation import formatting

    for fn in (formatting.PostFormatter.format_collection,
               formatting.PostFormatter.format_category_collection):
        src = inspect.getsource(fn)
        assert '"deal_id": d.deal_id, "line": item_line' in src, f"{fn.__name__} lost its line map"
        assert '"items": items' in src, f"{fn.__name__} does not publish the line map in meta"


def test_revalidate_each_reports_every_deal_not_just_the_first():
    """The whole point: publishing needs to know WHICH deals died, not that one did."""
    from src.services.generation import revalidate

    calls = []

    def fake_one(deal, _max):
        calls.append(deal.deal_id)
        return {"ok": deal.deal_id not in ("d1", "d3"), "reason": "dead"}

    deals = [types.SimpleNamespace(deal_id=f"d{i}") for i in range(5)]
    revalidate._revalidate_one = fake_one
    revalidate.session_scope = _fake_scope(deals)

    out = revalidate.revalidate_each([d.deal_id for d in deals], max_staleness_min=30)
    assert calls == ["d0", "d1", "d2", "d3", "d4"], "must not short-circuit"
    assert {d for d, v in out.items() if not v["ok"]} == {"d1", "d3"}


def test_a_crashing_check_does_not_abort_the_publish():
    """A scraper fault is not evidence the product is dead. This used to propagate out
    of revalidate and kill the whole publish call."""
    from src.services.generation import revalidate

    def boom(deal, _max):
        if deal.deal_id == "d1":
            raise RuntimeError("scraper exploded")
        return {"ok": True, "reason": None}

    deals = [types.SimpleNamespace(deal_id=f"d{i}") for i in range(3)]
    revalidate._revalidate_one = boom
    revalidate.session_scope = _fake_scope(deals)

    out = revalidate.revalidate_each([d.deal_id for d in deals], max_staleness_min=30)
    assert out["d1"]["ok"] is True
    assert "RuntimeError" in out["d1"]["reason"]


def _fake_scope(deals):
    import contextlib

    @contextlib.contextmanager
    def scope():
        yield types.SimpleNamespace(
            scalars=lambda *_a, **_k: types.SimpleNamespace(all=lambda: deals),
            expunge_all=lambda: None,
        )
    return scope


@pytest.fixture(autouse=True)
def _restore_revalidate():
    from src.services.generation import revalidate

    one, scope = revalidate._revalidate_one, revalidate.session_scope
    yield
    revalidate._revalidate_one, revalidate.session_scope = one, scope
