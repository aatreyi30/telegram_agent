"""complete() fails over to the other provider when the primary errors."""
from __future__ import annotations
import pytest


class _Settings:
    def __init__(self, provider, openai_key, groq_key):
        self.ai_provider = provider
        self.ai_model = "gpt-4o-mini-2024-07-18" if provider == "openai" else "llama-3.3-70b-versatile"
        self.openai_api_key = openai_key
        self.groq_api_key = groq_key
        self.ai_reasoning_effort = "medium"


def _client(monkeypatch, provider="openai", openai_key="ok", groq_key="gk"):
    from src.ai import client as mod
    monkeypatch.setattr(mod, "get_settings", lambda: _Settings(provider, openai_key, groq_key))
    monkeypatch.setattr(mod, "_record_trace", lambda **k: None)  # no DB
    return mod.AIClient()


def test_fails_over_to_groq_when_openai_errors(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setattr(c, "_client_for", lambda p: p)  # sentinel, not a real SDK
    seen = []

    def _openai(client, model, system, user, max_tokens, effort):
        seen.append(("openai", model))
        raise RuntimeError("Connection error.")

    def _groq(client, model, system, user, max_tokens):
        seen.append(("groq", model))
        return ("groq answer", None, 1, 1, None)

    monkeypatch.setattr(c, "_openai_complete", _openai)
    monkeypatch.setattr(c, "_groq_complete", _groq)

    assert c.complete("hi") == "groq answer"
    assert seen == [("openai", "gpt-4o-mini-2024-07-18"), ("groq", "llama-3.3-70b-versatile")]


def test_no_failover_when_backup_key_missing(monkeypatch):
    c = _client(monkeypatch, groq_key=None)
    monkeypatch.setattr(c, "_client_for", lambda p: p)
    monkeypatch.setattr(c, "_openai_complete",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    from src.ai.client import AIUnavailable
    with pytest.raises(AIUnavailable):
        c.complete("hi")


def test_primary_success_skips_fallback(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setattr(c, "_client_for", lambda p: p)
    monkeypatch.setattr(c, "_openai_complete",
                        lambda *a, **k: ("primary answer", None, 1, 1, None))
    monkeypatch.setattr(c, "_groq_complete",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    assert c.complete("hi") == "primary answer"