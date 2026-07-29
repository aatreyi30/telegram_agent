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
    assert intent["target_posts"] is None                # 9999 out of 1..350 -> dropped
    assert intent["exclude_merchants"] == {"amazon"}
    assert (intent["price_min"], intent["price_max"]) == (500, 1500)   # inverted -> swapped
    # Regression: an out-of-range count used to vanish with no trace — the AI's own
    # narrative would still parrot "9999" (it saw the raw text) while the deterministic
    # count silently stayed unchanged, a real prose/numbers contradiction. Must be
    # surfaced honestly instead.
    assert any("9999" in u and "1-350" in u for u in intent["unsupported"])


def test_ai_intent_extracts_weekly_total_period(monkeypatch):
    _mock_ai(monkeypatch,
             '{"target_posts": 40, "target_posts_period": "week", "interpretation": '
             '"total of 40 posts this week", "unsupported": []}')
    intent = extract_steer_intent("let us target 40 posts this week", _MERCH, _CATS)
    assert intent["target_posts"] == 40
    assert intent["target_posts_period"] == "week"


def test_ai_intent_bad_period_value_drops_to_none(monkeypatch):
    _mock_ai(monkeypatch, '{"target_posts": 12, "target_posts_period": "fortnight", "unsupported": []}')
    intent = extract_steer_intent("post 12", _MERCH, _CATS)
    assert intent["target_posts_period"] is None   # invalid enum value -> dropped, not trusted


def test_regex_fallback_detects_weekly_total_cue(monkeypatch):
    import src.ai.client as client_mod
    from src.ai.client import AIUnavailable

    def _boom(self, *a, **k):
        raise AIUnavailable("down")
    monkeypatch.setattr(client_mod.AIClient, "complete", _boom)

    weekly = extract_steer_intent("target 40 posts this week", _MERCH, _CATS)
    assert weekly["source"] == "regex"
    assert weekly["target_posts"] == 40
    assert weekly["target_posts_period"] == "week"

    daily = extract_steer_intent("make it 20", _MERCH, _CATS)
    assert daily["target_posts"] == 20
    assert daily["target_posts_period"] is None   # no weekly cue -> per-day default


def test_ai_intent_extracts_additional_posts_mode(monkeypatch):
    _mock_ai(monkeypatch,
             '{"target_posts": 20, "target_posts_mode": "additional", '
             '"interpretation": "20 fresh posts from now", "unsupported": []}')
    intent = extract_steer_intent("i want 20 posts today freshly from now", _MERCH, _CATS)
    assert intent["target_posts"] == 20
    assert intent["target_posts_mode"] == "additional"


def test_ai_intent_bad_mode_value_drops_to_none(monkeypatch):
    _mock_ai(monkeypatch, '{"target_posts": 12, "target_posts_mode": "bogus", "unsupported": []}')
    intent = extract_steer_intent("post 12", _MERCH, _CATS)
    assert intent["target_posts_mode"] is None   # invalid enum value -> dropped, not trusted


def test_regex_fallback_detects_additional_posts_cue(monkeypatch):
    """Regression: 'i want 20 posts today freshly from now' used to be read as a
    whole-day TOTAL of 20 — meaning already-posted slots ate into that count and only a
    handful of genuinely new slots got added. 'from now'/'more'/'additional' must be
    read as N NEW posts instead."""
    import src.ai.client as client_mod
    from src.ai.client import AIUnavailable

    def _boom(self, *a, **k):
        raise AIUnavailable("down")
    monkeypatch.setattr(client_mod.AIClient, "complete", _boom)

    fresh = extract_steer_intent("i want 20 posts today freshly from now", _MERCH, _CATS)
    assert fresh["source"] == "regex"
    assert fresh["target_posts"] == 20
    assert fresh["target_posts_mode"] == "additional"

    more = extract_steer_intent("make it 5 more", _MERCH, _CATS)
    assert more["target_posts"] == 5
    assert more["target_posts_mode"] == "additional"

    bare = extract_steer_intent("post 20 today", _MERCH, _CATS)
    assert bare["target_posts"] == 20
    assert bare["target_posts_mode"] is None   # no cue -> default whole-day total, unchanged


def test_regex_fallback_surfaces_out_of_range_count(monkeypatch):
    """Same honesty fix as the AI path, for when the AI itself is down: an out-of-range
    count (e.g. 400 > the 350 cap) must be surfaced in `unsupported`, not vanish silently."""
    import src.ai.client as client_mod
    from src.ai.client import AIUnavailable

    def _boom(self, *a, **k):
        raise AIUnavailable("down")
    monkeypatch.setattr(client_mod.AIClient, "complete", _boom)

    intent = extract_steer_intent("i want to focus 400 posts this week", _MERCH, _CATS)
    assert intent["source"] == "regex"
    assert intent["target_posts"] is None
    assert any("400" in u and "1-350" in u for u in intent["unsupported"])

    # 300 is now WITHIN the raised range (1..350) — must parse through cleanly, not drop.
    within = extract_steer_intent("i want to focus 300 posts this week", _MERCH, _CATS)
    assert within["target_posts"] == 300
    assert within["unsupported"] == []


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


def test_intent_prompt_warns_against_hard_pin_from_a_named_time_and_merchant():
    """Regression guard: "post amazon today morning 9" was mis-read by the model as a
    hard merchants_only filter, pinning ~27 of 35 remaining slots to amazon for the rest
    of the day instead of adding one amazon post near 9am. The system prompt must keep an
    explicit rule + example telling the model a time+merchant ask is a soft addition, not
    a whole-day-only filter — this just guards that the rule text isn't silently dropped."""
    assert "today morning 9" in directives._STEER_INTENT_SYSTEM
    assert "merchants_only EMPTY" in directives._STEER_INTENT_SYSTEM
