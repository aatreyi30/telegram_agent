"""Immutable raw snapshot storage.

Design principle (spec 08): *never modify raw collected data*. We write the raw
payload to a content-addressed file and record a RawSnapshot row pointing at
it. Files are named by sha256 so identical payloads dedupe naturally and raw
data is never overwritten.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.settings import get_settings
from src.db.models import RawSnapshot


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def store_raw(
    session: Session,
    *,
    source: str,
    source_ref: str | None,
    payload: Any,
    job_id: int | None = None,
    content_type: str = "application/json",
) -> RawSnapshot:
    """Persist a raw payload immutably and return its RawSnapshot row.

    ``payload`` may be bytes/str (stored as-is) or any JSON-serialisable object
    (serialised deterministically). Re-storing identical content returns the
    existing snapshot rather than duplicating the file.
    """
    settings = get_settings()

    if isinstance(payload, (bytes, bytearray)):
        data = bytes(payload)
    elif isinstance(payload, str):
        data = payload.encode("utf-8")
    else:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )

    digest = _sha256_bytes(data)

    existing = session.scalar(
        select(RawSnapshot).where(RawSnapshot.content_sha256 == digest)
    )
    if existing is not None:
        return existing

    # Content-addressed layout: raw/<source>/<aa>/<sha256>.<ext>
    ext = "json" if content_type == "application/json" else "bin"
    if content_type == "text/html":
        ext = "html"
    sub_dir: Path = settings.raw_snapshot_dir / source / digest[:2]
    sub_dir.mkdir(parents=True, exist_ok=True)
    file_path = sub_dir / f"{digest}.{ext}"
    if not file_path.exists():
        file_path.write_bytes(data)

    snapshot = RawSnapshot(
        source=source,
        source_ref=source_ref,
        content_sha256=digest,
        content_type=content_type,
        storage_path=str(file_path),
        byte_size=len(data),
        job_id=job_id,
    )
    session.add(snapshot)
    session.flush()  # assign id
    return snapshot
