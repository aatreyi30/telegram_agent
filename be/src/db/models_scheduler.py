"""Scheduler run log — every scheduled job records its execution here.

Per the Scheduler Architecture spec: start/end time, org, records processed,
success/failure counts, duration, retry count, status, and error details. This is
the audit trail the Schedulers UI reads.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class RunStatus:
    SUCCESS = "success"
    FAILED = "failed"
    LIMITED = "limited"     # ran, but produced no data due to access limits (honest)
    RETRYING = "retrying"


class SchedulerRun(Base):
    __tablename__ = "scheduler_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheduler_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    org_id: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default=RunStatus.SUCCESS)
    detail: Mapped[str | None] = mapped_column(Text)      # short note (e.g. "+40 posts")
    error: Mapped[str | None] = mapped_column(Text)
