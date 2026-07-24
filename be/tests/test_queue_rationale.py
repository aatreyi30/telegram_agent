# be/tests/test_queue_rationale.py
"""Regression test: queue() must surface GeneratedPost.strategy_rationale on each
item, same as drafts() already does — needed so the UI's reasoning popover works
for queued/published posts, not just drafts (see PR that added this field)."""
from __future__ import annotations
import os, tempfile
from datetime import datetime, timezone
import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    tmp = tempfile.mkdtemp()
    os.environ["DB_URL"] = f"sqlite:///{tmp}/test.db"
    os.environ["RAW_SNAPSHOT_DIR"] = f"{tmp}/raw"
    from src.config.settings import get_settings
    from src.db import session as sess
    get_settings.cache_clear(); sess.get_engine.cache_clear(); sess.get_sessionmaker.cache_clear()
    from src.db.session import init_db, session_scope
    from src.db.models_generation import GeneratedPost, PostStatus
    from src.db.models_automation import ScheduledPost, ScheduleStatus
    init_db()
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        gp = GeneratedPost(
            generated_at=now, post_type="single", rendered_text="x",
            deal_ids=["d1"], status=PostStatus.APPROVED,
            strategy_rationale={"kind": "single", "period": "today", "emoji_policy": {},
                                 "why_type": "peak hour for single deals"},
        )
        s.add(gp); s.flush()
        s.add(ScheduledPost(generated_post_id=gp.id, channel_ref="@test",
                             scheduled_at=now, idempotency_key="k1",
                             status=ScheduleStatus.QUEUED))
    yield


def test_queue_items_include_rationale():
    from src.controllers.service import queue
    result = queue(page=1, page_size=10)
    assert result["items"], "expected at least one queue item"
    item = result["items"][0]
    assert item["rationale"] is not None
    assert item["rationale"]["why_type"] == "peak hour for single deals"
