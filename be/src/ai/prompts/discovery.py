"""AI-arbitration prompt for ambiguous competitor-candidate verification,
consumed by `src.services.collection.discovery.verify_candidate`.

Unlike the other prompts in this package, this one is built per-call from a
brand name and a rendered candidate list, so it is centralized here as a
builder function rather than a flat string constant — the returned text is
byte-for-byte identical to what the call site used to construct inline."""

from __future__ import annotations


def verify_candidate_prompt(brand: str, lines: str) -> str:
    return (
        f"Which candidate Telegram channel, if any, is the OFFICIAL channel for the brand "
        f"\"{brand}\"? Consider only the given candidates.\n{lines}\n\n"
        "Reply with ONLY a compact JSON object: "
        '{"username": "<exact username or null>", "confidence": <0..1>}'
    )
