"""The PUBLISH_CHANNEL gate — the thing standing between a planned post and a real
channel. Gate 1 runs before any Telegram client is constructed, so these assert the
refusal WITHOUT touching the network: if a test here ever needs a session, the gate
has moved and the safety property is gone."""

from __future__ import annotations

import asyncio

import pytest

from src.services.generation.publishing import Publisher


# A post id nothing can have created. Past the channel gate the next step is the post
# lookup, which then always short-circuits on "not found" — so these tests stay network-
# free and independent of whatever rows other tests leave behind.
_NO_SUCH_POST = 10**9


def _attempt(publish_channel, target, post_id=_NO_SUCH_POST):
    """Run gate 1 for `target` with PUBLISH_CHANNEL=publish_channel."""
    pub = Publisher.__new__(Publisher)  # skip __init__ (settings/event bus not needed)

    class _S:
        telegram_session_name = "unused"
        telegram_api_id = 1
        telegram_api_hash = "x"

    _S.publish_channel = publish_channel
    pub.settings = _S()
    return asyncio.run(pub._check_and_publish(post_id, target, confirm=True))


def test_unset_publish_channel_holds_every_send():
    ok, note = _attempt(None, "@GrabOnIndiaOfficial")
    assert ok is False
    assert "no PUBLISH_CHANNEL configured" in note


def test_non_target_channel_is_refused():
    """The whole point: PUBLISH_CHANNEL=test means the real channel is refused even
    though it is the owned channel and the account may well have rights on it."""
    ok, note = _attempt("@my_test_channel", "@GrabOnIndiaOfficial")
    assert ok is False
    assert "not the configured PUBLISH_CHANNEL" in note
    assert "@my_test_channel" in note


@pytest.mark.parametrize("target", ["@my_test_channel", "my_test_channel", "@My_Test_Channel"])
def test_matching_target_passes_the_gate(target):
    """Matching must not depend on '@' or casing. Past the gate the post lookup
    reports the missing post — that message proves we cleared the channel gate."""
    ok, note = _attempt("@my_test_channel", target)
    assert ok is False
    assert "No generated post" in note
    assert "PUBLISH_CHANNEL" not in note


def test_private_channel_numeric_id_passes_the_gate():
    """A private channel's ref is a bare numeric id. It must survive the gate intact —
    lstrip('@') must not mangle it and it must compare equal to itself."""
    ok, note = _attempt("-1001234567890", "-1001234567890")
    assert ok is False
    assert "No generated post" in note, note


@pytest.mark.parametrize("raw,expected", [
    ("-1001234567890", "-1001234567890"),   # private channel id: NEVER '@'-prefixed
    ("1001234567890", "1001234567890"),
    ("my_test_channel", "@my_test_channel"),  # public handle: normalised to '@handle'
    ("@my_test_channel", "@my_test_channel"),
    ("  @spaced  ", "@spaced"),
    ("", None),                              # unset => auto-send held
    (None, None),
])
def test_publish_channel_normalisation(raw, expected):
    from src.config.settings import Settings

    s = Settings.__new__(Settings)
    s.publish_channel_raw = raw
    assert s.publish_channel == expected
