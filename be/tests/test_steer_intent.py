"""The universal steer: extract_steer_intent AI-interprets any free-text into a VALIDATED
structured intent — merchants/categories checked against the real feed (invalid dropped,
never invented), count clamped, times/prices sane — and falls back to the regex parsers
when the AI is unavailable, so steering never breaks."""
from __future__ import annotations

from src.services.generation import directives
from src.services.generation.directives import extract_steer_intent

_MERCH = ["amazon", "flipkart", "myntra", "ajio"]
_CATS = ["electronics-and-gadgets", "fashion-and-lifestyle", "general"]


def _mock_ai(monkeypatch, payload: str):
    import src.ai.client as client_mod
    monkeypatch.setattr(client_mod.AIClient, "complete", lambda self, *a, **k: payload)


def test_ai_intent_validated_against_feed(monkeypatch):
    # AI names a real + a fake merchant, a count, a price, a time, and an unsupported ask.
    _mock_ai(monkeypatch,
             '{"target_posts": 12, "merchants_only": ["flipkart", "nykaa"], '
             '"merchants_exclude": [], "categories_only": ["electronics-and-gadgets"], '
             '"categories_exclude": [], "price_max": 2000, "price_min": null, '
             '"after_time": "18:00", "before_time": null, "type_lean": "single", '
             '"pause": false, "interpretation": "Flipkart electronics under 2000, evening, 12 posts.", '
             '"unsupported": ["make captions punchier — set at post time, not the plan"]}')
    intent = extract_steer_intent("flipkart electronics under 2000, evening, 12 posts, punchier captions",
                                  _MERCH, _CATS)
    assert intent["source"] == "ai"
    assert intent["target_posts"] == 12
    assert intent["merchants"] == {"flipkart"}          # 'nykaa' dropped — not in feed
    assert intent["categories"] == {"electronics-and-gadgets"}
    assert intent["price_max"] == 2000
    assert intent["after_min"] == 18 * 60
    assert intent["type_lean"] == "single"
    assert intent["unsupported"] and "captions" in intent["unsupported"][0]


def test_ai_intent_clamps_and_sanitises(monkeypatch):
    _mock_ai(monkeypatch,
             '{"target_posts": 9999, "merchants_only": [], "merchants_exclude": ["amazon"], '
             '"price_min": 1500, "price_max": 500, "pause": false, "interpretation": "x", "unsupported": []}')
    intent = extract_steer_intent("avoid amazon, over 1500 under 500, post 9999", _MERCH, _CATS)
    assert intent["target_posts"] is None                # 9999 out of 1..200 -> dropped
    assert intent["exclude_merchants"] == {"amazon"}
    assert (intent["price_min"], intent["price_max"]) == (500, 1500)   # inverted -> swapped


def test_ai_failure_falls_back_to_regex(monkeypatch):
    import src.ai.client as client_mod
    from src.ai.client import AIUnavailable

    def _boom(self, *a, **k):
        raise AIUnavailable("down")
    monkeypatch.setattr(client_mod.AIClient, "complete", _boom)

    intent = extract_steer_intent("avoid ajio, make it 15", _MERCH, _CATS)
    assert intent["source"] == "regex"
    assert intent["target_posts"] == 15
    assert intent["exclude_merchants"] == {"ajio"}


def test_pause_detected(monkeypatch):
    _mock_ai(monkeypatch, '{"pause": true, "interpretation": "stop posting", "unsupported": []}')
    assert extract_steer_intent("pause everything", _MERCH, _CATS)["pause"] is True


def test_empty_directive_is_empty_intent():
    intent = extract_steer_intent("", _MERCH, _CATS)
    assert intent["source"] == "empty" and intent["target_posts"] is None and intent["pause"] is False


def test_unparseable_ai_reply_falls_back(monkeypatch):
    _mock_ai(monkeypatch, "sorry, I could not do that")   # no JSON
    intent = extract_steer_intent("only flipkart", _MERCH, _CATS)
    assert intent["source"] == "regex"
    assert intent["merchants"] == {"flipkart"}
