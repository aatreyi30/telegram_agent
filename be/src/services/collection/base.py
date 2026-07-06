"""Base collector contract + the job runner that wraps every collection run.

Every collector is synchronous from the runner's perspective (async collectors
wrap their own event loop internally). The runner owns the CollectionJob
lifecycle, observability counters, retry accounting, and the guarantee that a
failure never corrupts existing data (each collector uses its own transactions;
the runner only records job metadata).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.db.models import CollectionJob, JobStatus
from src.db.session import session_scope
from src.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CollectorResult:
    """What a collector reports back to the runner."""

    processed: int = 0
    added: int = 0
    updated: int = 0
    skipped: int = 0
    # When a collector cannot run because its source is unavailable, it sets
    # skipped_reason instead of raising — the job is SKIPPED, not FAILED.
    skipped_reason: str | None = None
    detail: dict = field(default_factory=dict)


class CollectorError(Exception):
    """Raised for transient/permanent collection failures (triggers retry logic)."""


class BaseCollector:
    #: stable identifier, used as CollectionJob.job_type
    name: str = "base"
    #: whether transient failures should be retried by the runner
    retryable: bool = True

    def available(self) -> tuple[bool, str | None]:
        """Return (is_available, reason_if_not). Default: always available."""
        return True, None

    def run(self, job: CollectionJob) -> CollectorResult:  # pragma: no cover - abstract
        raise NotImplementedError


class JobRunner:
    """Executes a collector inside a fully-tracked CollectionJob row."""

    def run_collector(
        self,
        collector: BaseCollector,
        *,
        collection_type: str,
        target: str | None = None,
        priority: int = 100,
        max_retries: int = 3,
        payload: dict | None = None,
    ) -> CollectionJob:
        # 1) create the job row
        with session_scope() as s:
            job = CollectionJob(
                job_type=collector.name,
                collection_type=collection_type,
                target=target,
                priority=priority,
                status=JobStatus.QUEUED,
                max_retries=max_retries,
                payload=payload,
            )
            s.add(job)
            s.flush()
            job_id = job.id

        # 2) short-circuit if the source is unavailable (skip, don't fail)
        ok, reason = collector.available()
        if not ok:
            logger.info("[%s] source unavailable -> SKIPPED: %s", collector.name, reason)
            self._finalize(job_id, JobStatus.SKIPPED, error=reason)
            return self._reload(job_id)

        # 3) run with retry accounting
        self._mark_running(job_id)
        started = time.monotonic()
        attempt = 0
        while True:
            try:
                result = collector.run(self._reload(job_id))
                duration_ms = int((time.monotonic() - started) * 1000)
                if result.skipped_reason:
                    self._finalize(
                        job_id,
                        JobStatus.SKIPPED,
                        error=result.skipped_reason,
                        duration_ms=duration_ms,
                        result=result,
                    )
                else:
                    self._finalize(
                        job_id,
                        JobStatus.COMPLETED,
                        duration_ms=duration_ms,
                        result=result,
                    )
                    logger.info(
                        "[%s] done target=%s processed=%d added=%d updated=%d skipped=%d",
                        collector.name,
                        target,
                        result.processed,
                        result.added,
                        result.updated,
                        result.skipped,
                    )
                return self._reload(job_id)
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                logger.warning(
                    "[%s] attempt %d failed: %s", collector.name, attempt, exc
                )
                if collector.retryable and attempt <= max_retries:
                    self._bump_retry(job_id, attempt, str(exc))
                    time.sleep(min(2 ** attempt, 30))  # capped exponential backoff
                    continue
                duration_ms = int((time.monotonic() - started) * 1000)
                self._finalize(
                    job_id, JobStatus.FAILED, error=str(exc), duration_ms=duration_ms
                )
                logger.error("[%s] permanently failed: %s", collector.name, exc)
                return self._reload(job_id)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _reload(job_id: int) -> CollectionJob:
        with session_scope() as s:
            job = s.get(CollectionJob, job_id)
            s.expunge_all()
            return job

    @staticmethod
    def _mark_running(job_id: int) -> None:
        with session_scope() as s:
            job = s.get(CollectionJob, job_id)
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)

    @staticmethod
    def _bump_retry(job_id: int, attempt: int, error: str) -> None:
        with session_scope() as s:
            job = s.get(CollectionJob, job_id)
            job.status = JobStatus.RETRY
            job.retry_count = attempt
            job.error_message = error

    @staticmethod
    def _finalize(
        job_id: int,
        status: str,
        *,
        error: str | None = None,
        duration_ms: int | None = None,
        result: CollectorResult | None = None,
    ) -> None:
        with session_scope() as s:
            job = s.get(CollectionJob, job_id)
            job.status = status
            job.finished_at = datetime.now(timezone.utc)
            if duration_ms is not None:
                job.duration_ms = duration_ms
            if error is not None:
                job.error_message = error
            if result is not None:
                job.records_processed = result.processed
                job.records_added = result.added
                job.records_updated = result.updated
                job.records_skipped = result.skipped
