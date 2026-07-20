"""Persisted trace of every product AI call.

Written at the single choke point (``AIClient.complete``/``agentic``) so every
LLM call the product makes is observable: exact input (system + user), output,
reasoning summary + token counts, model/provider, latency, which call site and
channel it served, and success/error. This is the evaluation + migration ledger
— replay any row's input against a new model and diff the output.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class AITrace(Base):
    __tablename__ = "ai_traces"
    __table_args__ = (Index("ix_ai_traces_call_created", "call", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call: Mapped[str | None] = mapped_column(String(48))          # 'day_plan'|'week_plan'|'copywriter_deal'|...
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"))
    provider: Mapped[str] = mapped_column(String(16), nullable=False)   # 'openai'|'groq'
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    reasoning_effort: Mapped[str | None] = mapped_column(String(16))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    input: Mapped[str] = mapped_column(Text, nullable=False)       # the user message
    output: Mapped[str | None] = mapped_column(Text)
    reasoning: Mapped[str | None] = mapped_column(Text)            # reasoning summary, when the provider returns one
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[int] = mapped_column(Integer, nullable=False, default=1)   # 1 ok, 0 error
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
