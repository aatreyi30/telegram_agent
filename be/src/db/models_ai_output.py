"""Phase 0.2 storage — persisted AI outputs.

Every generated piece of AI text (daily/weekly briefings, coach answers, the
weekly retro narrative) is stored here instead of being dropped on the floor
once printed/returned. Gives the AI (and operators) a memory of what it said
and when, and a stable ``prompt_context_hash`` to later tell whether the same
grounding context produced a different answer.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class AIOutput(Base):
    __tablename__ = "ai_outputs"
    __table_args__ = (Index("ix_ai_outputs_kind_created", "kind", "channel_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)   # 'daily_briefing'|'weekly_briefing'|'coach_qa'|'retro_narrative'
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"))
    prompt_context_hash: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
