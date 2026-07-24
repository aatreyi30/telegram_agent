"""Grounded narrative writer for deterministic engine outputs.

Used by the reasoning, learning, and growth engines to turn structured evidence
into one sharp, specific sentence instead of picking from a fixed template menu.
Every call is strictly grounded: the model may only reference numbers/fields
present in the evidence dict handed to it, and it is instructed to add the
"why it matters / why this helps" layer rather than restate the observation
verbatim — this is what stops recommendations from repeating what the Learnings
section already said.

This runs during scheduled pipeline jobs (reasoning/growth engines), never on a
user-facing request path, so per-call latency is not a concern. It must never
break the pipeline: any failure (no API key, rate limit, network error) falls
back to the caller-supplied deterministic string.
"""

from __future__ import annotations

from src.ai.client import AIClient, AIUnavailable
from src.ai.context import to_json
from src.ai.prompts import INSIGHT_LINE_SYSTEM as _INSIGHT_LINE_SYSTEM
from src.logger import get_logger

logger = get_logger(__name__)


def narrate(kind: str, observation: str, evidence: dict, fallback: str) -> str:
    """Best-effort grounded one-liner. Always returns a usable string — falls
    back to `fallback` (which should already be a good, data-specific sentence
    on its own) on any AI unavailability or failure."""
    try:
        ai = AIClient()
        ok, _ = ai.available()
        if not ok:
            return fallback
        user = (f"CONTEXT: {kind}\nOBSERVATION: {observation}\n\n"
                f"EVIDENCE:\n{to_json(evidence)}")
        text = ai.complete(user, system_extra=_INSIGHT_LINE_SYSTEM, max_tokens=120, effort="low",
                           trace_call="narrate")
        text = text.strip().strip('"').strip()
        return text or fallback
    except AIUnavailable:
        return fallback
    except Exception:
        logger.exception("[insight_writer] narration failed for kind=%s, using fallback", kind)
        return fallback
