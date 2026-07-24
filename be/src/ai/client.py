"""Grounded AI client — the single choke point for every product AI call.

Provider-selectable (``AI_PROVIDER``):
  * ``openai`` — reasoning models (default ``gpt-5-mini-2025-08-07``); sends
    ``reasoning_effort`` + ``max_completion_tokens`` and omits temperature
    (reasoning models only accept the default).
  * ``groq`` — OpenAI-compatible chat completions (``llama-3.3-70b-versatile``);
    ``effort`` is a no-op, temperature kept low for factuality.

Both providers expose ``chat.completions.create``, so one code path serves both.
It prepends a grounding system prompt that forbids inventing facts, and — best
effort — records every call to ``ai_traces`` (input, output, reasoning tokens,
latency, model, call site, channel) for evaluation and the migration.

If the active provider has no API key it reports itself UNAVAILABLE (like every
other external dependency) rather than failing loudly.
"""

from __future__ import annotations

import json
import time

from src.ai.prompts import GROUNDING_SYSTEM
from src.config.settings import get_settings
from src.logger import get_logger

logger = get_logger(__name__)


class AIUnavailable(RuntimeError):
    pass


def _record_trace(**fields) -> None:
    """Best-effort persist of one AI call. Never raises into the caller's path."""
    try:
        from src.db.models_ai_trace import AITrace
        from src.db.session import session_scope
        with session_scope() as s:
            s.add(AITrace(**fields))
    except Exception as exc:  # tracing must never break a real AI call
        logger.debug("ai trace write failed: %s", exc)


# Reasoning tokens count against the Responses API's max_output_tokens, so the visible
# answer needs headroom on top of the caller's budget or it gets truncated mid-thought.
# ponytail: fixed headroom, widen if higher reasoning efforts truncate real output.
_REASONING_HEADROOM = 2000

# OpenAI model families that accept reasoning params. A CHAT model (gpt-4o*, gpt-4.1*)
# rejects `reasoning`/`reasoning_effort` with a 400, so the switch is per-MODEL, not per
# provider — "openai" alone doesn't tell you which shape the request must take.
_REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def is_reasoning_model(model: str) -> bool:
    return (model or "").lower().startswith(_REASONING_MODEL_PREFIXES)


def _cc_usage(resp) -> tuple[int | None, int | None, int | None]:
    """(prompt, completion, reasoning) tokens from a chat.completions response (groq)."""
    u = getattr(resp, "usage", None)
    if u is None:
        return None, None, None
    details = getattr(u, "completion_tokens_details", None)
    reasoning = getattr(details, "reasoning_tokens", None) if details is not None else None
    return getattr(u, "prompt_tokens", None), getattr(u, "completion_tokens", None), reasoning


def _reasoning_summary(resp) -> str | None:
    """Diarized reasoning summary text from a Responses API result (not raw CoT —
    OpenAI only exposes a model-written summary, enabled via reasoning.summary)."""
    parts = []
    for item in getattr(resp, "output", None) or []:
        if getattr(item, "type", None) == "reasoning":
            for sm in getattr(item, "summary", None) or []:
                t = getattr(sm, "text", None)
                if t:
                    parts.append(t)
    return "\n\n".join(parts) or None


class AIClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.provider = self.settings.ai_provider
        self.model = self.settings.ai_model
        self._client = None

    def _api_key(self) -> str | None:
        return (self.settings.openai_api_key if self.provider == "openai"
                else self.settings.groq_api_key)

    def available(self) -> tuple[bool, str | None]:
        if not self._api_key():
            key = "OPENAI_API_KEY" if self.provider == "openai" else "GROQ_API_KEY"
            return False, (f"AI layer not configured. Set {key} in .env to enable "
                           "plans, AI post copy, and insights.")
        return True, None

    def _get_client(self):
        if self._client is None:
            if self.provider == "openai":
                from openai import OpenAI
                self._client = OpenAI(api_key=self.settings.openai_api_key)
            else:
                from groq import Groq
                self._client = Groq(api_key=self.settings.groq_api_key)
        return self._client

    @property
    def uses_reasoning(self) -> bool:
        """True when the ACTIVE model takes reasoning params. Groq's chat models and
        OpenAI's chat models (gpt-4o*, gpt-4.1*) both take the plain chat shape."""
        return self.provider == "openai" and is_reasoning_model(self.model)

    def _params(self, max_tokens: int, effort: str) -> dict:
        """Request params for the ACTIVE model. Reasoning models use
        max_completion_tokens + reasoning_effort and reject a custom temperature;
        chat models are the reverse and 400 on reasoning_effort."""
        if self.uses_reasoning:
            return {"max_completion_tokens": max_tokens, "reasoning_effort": effort}
        return {"max_tokens": max_tokens, "temperature": 0.3}

    def complete(self, user: str, *, system_extra: str = "", max_tokens: int = 4000,
                 effort: str = "medium", trace_call: str | None = None,
                 channel_id: int | None = None) -> str:
        """One-shot grounded completion. Returns the text response and records a trace.

        OpenAI reasoning models go through the Responses API so we capture the diarized
        reasoning summary; ``effort`` maps to ``reasoning.effort`` (no-op on Groq).
        ``trace_call``/``channel_id`` label the persisted trace row.
        """
        ok, reason = self.available()
        if not ok:
            raise AIUnavailable(reason)
        client = self._get_client()
        system = GROUNDING_SYSTEM + (("\n\n" + system_extra) if system_extra else "")
        effort = effort if self.provider == "openai" else self.settings.ai_reasoning_effort
        started = time.monotonic()
        try:
            if self.provider == "openai":
                out, reasoning, pt, ct, rt = self._openai_complete(client, system, user,
                                                                   max_tokens, effort)
            else:
                out, reasoning, pt, ct, rt = self._groq_complete(client, system, user, max_tokens)
        except Exception as exc:
            logger.warning("AI completion failed: %s", exc)
            _record_trace(call=trace_call, channel_id=channel_id, provider=self.provider,
                          model=self.model,
                          reasoning_effort=effort if self.uses_reasoning else None,
                          system_prompt=system, input=user, ok=0, error=str(exc),
                          latency_ms=int((time.monotonic() - started) * 1000))
            raise AIUnavailable(str(exc)) from exc
        _record_trace(call=trace_call, channel_id=channel_id, provider=self.provider,
                      model=self.model,
                      reasoning_effort=effort if self.uses_reasoning else None,
                      system_prompt=system, input=user, output=out, reasoning=reasoning,
                      prompt_tokens=pt, completion_tokens=ct, reasoning_tokens=rt,
                      latency_ms=int((time.monotonic() - started) * 1000))
        return out

    def _openai_complete(self, client, system: str, user: str, max_tokens: int, effort: str):
        """Responses API — returns (text, reasoning_summary, prompt_tok, output_tok, reasoning_tok).

        Chat models (gpt-4o*, gpt-4.1*) work here too, but reject the `reasoning` param
        and need no headroom — nothing is spent thinking."""
        kwargs = {"model": self.model, "instructions": system, "input": user,
                  "max_output_tokens": max_tokens}
        if self.uses_reasoning:
            kwargs["reasoning"] = {"effort": effort, "summary": "auto"}
            kwargs["max_output_tokens"] = max_tokens + _REASONING_HEADROOM
        resp = client.responses.create(**kwargs)
        u = getattr(resp, "usage", None)
        details = getattr(u, "output_tokens_details", None) if u else None
        return (
            (getattr(resp, "output_text", "") or "").strip(),
            _reasoning_summary(resp),
            getattr(u, "input_tokens", None) if u else None,
            getattr(u, "output_tokens", None) if u else None,
            getattr(details, "reasoning_tokens", None) if details else None,
        )

    def _groq_complete(self, client, system: str, user: str, max_tokens: int):
        """Chat Completions — returns (text, None, prompt_tok, completion_tok, reasoning_tok)."""
        resp = client.chat.completions.create(
            model=self.model, max_tokens=max_tokens, temperature=0.3,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        pt, ct, rt = _cc_usage(resp)
        return (resp.choices[0].message.content or "").strip(), None, pt, ct, rt

    def agentic(self, user: str, tools: list[dict], tool_runner, *,
                system_extra: str = "", max_tokens: int = 4000,
                max_iterations: int = 8) -> str:
        """Manual agentic loop: the model calls read-only tools over our engines until
        it can answer. `tools` are given in the simple {name, description, input_schema}
        form and converted to OpenAI/Groq function schema here. `tool_runner(name, input)
        -> str` executes each tool. (CLI growth coach only; not traced.)"""
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
        params = self._params(max_tokens, self.settings.ai_reasoning_effort)
        for _ in range(max_iterations):
            try:
                resp = client.chat.completions.create(
                    model=self.model, tools=oai_tools, tool_choice="auto",
                    messages=messages, **params,
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
