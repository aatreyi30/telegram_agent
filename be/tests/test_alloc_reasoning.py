"""The LLM-authored deal-type 'Why' reasoning must stay grounded: a sentence citing a
number NOT in the deterministic inputs is dropped (the row keeps its deterministic
reasoning), while a fully-grounded sentence is kept verbatim."""
from __future__ import annotations

from src.controllers import service


_ALLOC = [
    {"deal_type": "Single deal", "post_type": "single_deal", "target_posts": 21,
     "avg_views_per_post": 526, "views_sample": 1240},
    {"deal_type": "Loot / Multi deal", "post_type": "loot_deal", "target_posts": 20,
     "avg_views_per_post": 518, "views_sample": 900},
]


def test_grounded_kept_invented_dropped(monkeypatch):
    import src.ai.client as client_mod

    fake = (
        '{"single_deal":"Singles average 526 views/post across 1240 measured posts, so they lead the mix.",'
        '"loot_deal":"Loot boards convert 94% better than singles, so they get priority."}'
    )
    monkeypatch.setattr(client_mod.AIClient, "complete", lambda self, *a, **k: fake)

    out = service._llm_allocation_reasoning(_ALLOC)
    # grounded single reason (526 + 1240 are real views/sample) survives verbatim
    assert out.get("single_deal") and "526" in out["single_deal"]
    # loot reason invents "94" (a made-up conversion figure) -> dropped, not trusted
    assert "loot_deal" not in out
    # never emits a post count (rebucketed later -> would go stale)
    assert "21" not in (out.get("single_deal") or "") and "20" not in (out.get("single_deal") or "")


def test_ai_unavailable_returns_empty(monkeypatch):
    import src.ai.client as client_mod
    from src.ai.client import AIUnavailable

    def _boom(self, *a, **k):
        raise AIUnavailable("down")

    monkeypatch.setattr(client_mod.AIClient, "complete", _boom)
    assert service._llm_allocation_reasoning(_ALLOC) == {}