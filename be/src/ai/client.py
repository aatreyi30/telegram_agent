"""Grounded AI client — Groq (OpenAI-compatible, fast).

The single choke point for every AI call. It prepends a grounding system prompt
that forbids inventing facts. If no API key is configured it reports itself
UNAVAILABLE (like every other external dependency) rather than failing loudly.

Provider: Groq (`groq` SDK, OpenAI-compatible chat completions + tool use).
Model is config-driven (`AI_MODEL`, default `llama-3.3-70b-versatile`).
"""

from __future__ import annotations

import json

from src.ai.prompts import GROUNDING_SYSTEM
from src.config.settings import get_settings
from src.logger import get_logger

logger = get_logger(__name__)


class AIUnavailable(RuntimeError):
    pass


class AIClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.model = self.settings.ai_model
        self._client = None

    def available(self) -> tuple[bool, str | None]:
        if not self.settings.groq_api_key:
            return False, ("AI layer not configured. Set GROQ_API_KEY in .env to enable "
                           "briefings, AI post copy, and the growth coach.")
        return True, None

    def _get_client(self):
        if self._client is None:
            from groq import Groq
            self._client = Groq(api_key=self.settings.groq_api_key)
        return self._client

    def complete(self, user: str, *, system_extra: str = "", max_tokens: int = 4000,
                 effort: str = "medium") -> str:
        """One-shot grounded completion. Returns the text response.

        `effort` is accepted for call-site parity with other providers but is a no-op
        on Groq (no thinking-budget parameter); we keep temperature low for factuality.
        """
        ok, reason = self.available()
        if not ok:
            raise AIUnavailable(reason)
        client = self._get_client()
        system = GROUNDING_SYSTEM + (("\n\n" + system_extra) if system_extra else "")
        try:
            resp = client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=0.3,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
            )
        except Exception as exc:
            logger.warning("AI completion failed: %s", exc)
            raise AIUnavailable(str(exc)) from exc
        return (resp.choices[0].message.content or "").strip()

    def agentic(self, user: str, tools: list[dict], tool_runner, *,
                system_extra: str = "", max_tokens: int = 4000,
                max_iterations: int = 8) -> str:
        """Manual agentic loop: the model calls read-only tools over our engines until
        it can answer. `tools` are given in the simple {name, description, input_schema}
        form and converted to OpenAI/Groq function schema here. `tool_runner(name, input)
        -> str` executes each tool."""
        ok, reason = self.available()
        if not ok:
            raise AIUnavailable(reason)
        client = self._get_client()
        system = GROUNDING_SYSTEM + (("\n\n" + system_extra) if system_extra else "")
        oai_tools = [{
            "type": "function",
            "function": {"name": t["name"], "description": t["description"],
                         "parameters": t.get("input_schema", {"type": "object", "properties": {}})},
        } for t in tools]

        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        for _ in range(max_iterations):
            try:
                resp = client.chat.completions.create(
                    model=self.model, max_tokens=max_tokens, temperature=0.3,
                    tools=oai_tools, tool_choice="auto", messages=messages,
                )
            except Exception as exc:
                logger.warning("AI agentic completion failed: %s", exc)
                raise AIUnavailable(str(exc)) from exc
            msg = resp.choices[0].message
            if msg.tool_calls:
                messages.append({
                    "role": "assistant", "content": msg.content or "",
                    "tool_calls": [{
                        "id": tc.id, "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    } for tc in msg.tool_calls],
                })
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    out = tool_runner(tc.function.name, args)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
                continue
            return (msg.content or "").strip()
        return "Reached the reasoning-step limit before completing the answer."
