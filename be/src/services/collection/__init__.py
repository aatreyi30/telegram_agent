"""Data Collection Engine (Phase 1).

The ONLY layer permitted to talk to external data sources (spec 08). Every
collector follows the same lifecycle and produces (a) an immutable raw snapshot
and (b) structured rows, then emits events. No intelligence lives here.
"""
