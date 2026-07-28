"""A send that already went out must NEVER be re-sent. If a prior attempt recorded a
Telegram message id but its status write was lost to a transient DB lock, the retry must
detect the recorded id and skip the network send — the guard against double-posting. And
the tiny status/message-id writes must survive a transient lock rather than being lost."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import delete
from sqlalchemy.exc import OperationalError

from src.db.models_generation import GeneratedPost, PostStatus
from src.db.session import session_scope
from src.services.generation import publishing
from src.services.generation.publishing import Publisher, _write_with_retry


def _publisher(publish_channel):
    pub = Publisher.__new__(Publisher)  # skip __init__ — only settings.publish_channel is read

    class _S:
        telegram_session_name = "unused"
        telegram_api_id = 1
        telegram_api_hash = "x"

    _S.publish_channel = publish_channel
    pub.settings = _S()
    return pub


def test_already_sent_post_is_not_resent():
    """A post carrying a telegram_message_id from a prior send is reported as already
    sent WITHOUT touching the network — no duplicate message."""
    with session_scope() as s:
        post = GeneratedPost(
            generated_at=datetime.now(timezone.utc), post_type="single", deal_ids=[],
            rendered_text="hi", status=PostStatus.DRAFT, telegram_message_id=81,
            channel_ref="@my_test_channel")
        s.add(post)
        s.flush()
        pid = post.id
    try:
        ok, note = asyncio.run(
            _publisher("@my_test_channel")._check_and_publish(pid, "@my_test_channel", confirm=True))
        assert ok is True, note
        assert "message id=81" in note and "not resending" in note.lower(), note
    finally:
        with session_scope() as s:
            s.execute(delete(GeneratedPost).where(GeneratedPost.id == pid))


def test_write_with_retry_recovers_from_transient_lock():
    """A single-row write that hits 'database is locked' once is retried, not lost."""
    calls = {"n": 0}

    def _fn(_s):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("UPDATE ...", {}, Exception("database is locked"))

    orig_sleep = publishing.time.sleep
    publishing.time.sleep = lambda *_a, **_k: None  # don't actually wait
    try:
        _write_with_retry(_fn)
    finally:
        publishing.time.sleep = orig_sleep
    assert calls["n"] == 2, calls  # failed once, retried, succeeded


def test_write_with_retry_reraises_non_lock_errors():
    """A non-lock error is a real failure — surface it immediately, don't retry-swallow."""
    def _fn(_s):
        raise OperationalError("UPDATE ...", {}, Exception("no such column: bogus"))

    orig_sleep = publishing.time.sleep
    publishing.time.sleep = lambda *_a, **_k: None
    try:
        raised = False
        try:
            _write_with_retry(_fn)
        except OperationalError:
            raised = True
        assert raised
    finally:
        publishing.time.sleep = orig_sleep