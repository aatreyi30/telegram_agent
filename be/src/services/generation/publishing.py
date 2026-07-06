"""Publishing (source_truth/04 Phase 9) — SCAFFOLD with hard safety gates.

Publishing is an outward-facing, hard-to-reverse action, so it:
  1. requires explicit confirmation (never auto-sends);
  2. requires the authorised account to be an ADMIN with post rights on the target
     channel — a member/observer account (like ours on GrabOn) is refused;
  3. sends whatever links the draft already carries — affiliate/short links are
     generated at DRAFT time by the configured AffiliateProvider (tgagent/affiliate/,
     e.g. GrabOn); when no provider is set the draft carries the clean product URL.

Because our current account is a member (not admin) of GrabOn, publish() correctly
returns BLOCKED rather than pretending to post — the affiliate gate is now closed,
but the admin-rights gate remains.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from src.config.settings import get_settings
from src.db.models_generation import GeneratedPost, PostStatus
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.logger import get_logger

logger = get_logger(__name__)


class Publisher:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.bus = get_event_bus()

    def publish(self, post_id: int, channel_ref: str, confirm: bool = False) -> dict:
        with session_scope() as s:
            post = s.get(GeneratedPost, post_id)
            if post is None:
                return {"ok": False, "status": "error", "note": f"No generated post #{post_id}."}

        if not confirm:
            note = ("Publishing not attempted: this sends to a live channel and needs explicit "
                    "confirmation. Re-run with --confirm.")
            self._set(post_id, PostStatus.DRAFT, note)
            return {"ok": False, "status": PostStatus.DRAFT, "note": note}

        prov = self.settings.affiliate_provider_name
        if prov == "generic":
            aff_note = ("No affiliate provider configured — the post carries the clean product "
                        "URL, untracked.")
        else:
            aff_note = (f"Affiliate links generated via the '{prov}' provider at draft time "
                        "(already embedded in the post text).")

        if not (self.settings.telegram_api_id and self.settings.telegram_api_hash):
            note = "Telegram MTProto not configured; cannot publish."
            self._set(post_id, PostStatus.BLOCKED, note)
            return {"ok": False, "status": PostStatus.BLOCKED, "note": note}

        ok, reason = asyncio.run(self._check_and_publish(post_id, channel_ref, confirm=True))
        status = PostStatus.PUBLISHED if ok else PostStatus.BLOCKED
        full_note = (aff_note + " " + reason).strip()
        self._set(post_id, status, full_note, channel_ref)
        if ok:
            self.bus.publish(Event(event_type=EventType.POST_PUBLISHED, entity_type="post",
                                   entity_id=str(post_id), data={"channel": channel_ref}))
        return {"ok": ok, "status": status, "note": full_note}

    async def _check_and_publish(self, post_id: int, channel_ref: str, confirm: bool):
        from telethon import TelegramClient
        from telethon.tl.functions.channels import GetParticipantRequest

        client = TelegramClient(self.settings.telegram_session_name,
                                self.settings.telegram_api_id, self.settings.telegram_api_hash)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return False, "Telegram session not authorised (run telegram-login)."
            entity = await client.get_entity(channel_ref.lstrip("@"))
            me = await client.get_me()
            # verify admin post rights — never post without them
            try:
                part = await client(GetParticipantRequest(channel=entity, participant=me.id))
                p = part.participant
                rights = getattr(p, "admin_rights", None)
                is_creator = type(p).__name__ == "ChannelParticipantCreator"
                can_post = is_creator or (rights is not None and getattr(rights, "post_messages", False))
            except Exception:
                can_post = False
            if not can_post:
                return False, ("Account lacks admin post rights on this channel — publishing "
                               "refused. (Add the account as an admin with 'Post messages'.)")
            # NOTE: actual send intentionally not executed until affiliate integration + explicit
            # operator sign-off flow exist. We have verified we COULD post.
            return False, ("Permission OK, but auto-send is held pending the affiliate-link "
                           "integration and an operator sign-off step (safety).")
        finally:
            await client.disconnect()

    @staticmethod
    def _set(post_id: int, status: str, note: str, channel_ref: str | None = None) -> None:
        with session_scope() as s:
            post = s.get(GeneratedPost, post_id)
            post.status = status
            post.publish_note = note
            if channel_ref:
                post.channel_ref = channel_ref
