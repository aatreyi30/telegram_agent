"""AI layer (Phase 8 / AI Reporting + agentic coach).

A GROUNDED Claude layer on top of the deterministic engines. Per the source-truth
rules ("not a ChatGPT wrapper", "no hallucination", "AI understands the data, it
does not invent it"), every AI call is constrained to use ONLY the verified engine
outputs passed to it as data — it narrates, explains, formats, and reasons over
that data, and says so explicitly when the data is insufficient.
"""
