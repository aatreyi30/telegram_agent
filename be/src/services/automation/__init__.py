"""Phase 11 — Automation Engine.

Turns approved drafts + the campaign plan's posting windows into a scheduled
posting queue, and processes that queue with retry/backoff and multi-channel
support. The actual send stays gated behind channel admin rights + affiliate
integration (see generation/publishing.py) — automation records blocked sends
honestly rather than faking delivery.
"""
