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


async def resolve_entity(client, chat_ref: str):
    """Resolve a chat ref to a Telethon entity.

    ``get_entity`` handles a public '@username' fine, but cannot cold-resolve a bare
    numeric id (a PRIVATE channel's only ref) in a fresh process — the id has to
    already be in its session cache. Fall back to scanning live dialogs by id or exact
    name, which always works for a chat the account is actually in.
    """
    try:
        return await client.get_entity(chat_ref)
    except (ValueError, TypeError):
        pass
    try:
        target_id = int(chat_ref)
    except ValueError:
        target_id = None
    async for d in client.iter_dialogs():
        if (target_id is not None and d.id == target_id) or d.name == chat_ref:
            return d.entity
    raise ValueError(f"Could not resolve chat {chat_ref!r} — not in get_entity's cache and no "
                     f"matching dialog found. Check the ref with `tgagent dev-chats`.")


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

        # Phase 0.3 — never publish a stale/dead/repriced deal: re-check every
        # deal this post carries right before the actual send.
        from src.services.generation.revalidate import revalidate_deals

        stale_min = self.settings.prepublish_max_staleness_min
        verdict = revalidate_deals(post.deal_ids or [], max_staleness_min=stale_min)
        if not verdict["ok"]:
            note = f"blocked_stale: {verdict['reason']}"
            self._set(post_id, PostStatus.BLOCKED, note)
            # notification_engine already flags BLOCKED posts; nothing else needed this phase
            return {"ok": False, "status": PostStatus.BLOCKED, "note": note}

        ok, reason = asyncio.run(self._check_and_publish(post_id, channel_ref, confirm=True))
        status = PostStatus.PUBLISHED if ok else PostStatus.BLOCKED
        full_note = (aff_note + " " + reason).strip()
        self._set(post_id, status, full_note, channel_ref)
        if ok:
            self.bus.publish(Event(event_type=EventType.POST_PUBLISHED, entity_type="post",
                                   entity_id=str(post_id), data={"channel": channel_ref}))
            # Phase 2.2 -- re-predict with fresh features at publish time and
            # best-effort backfill the PostPrediction<->post_id link. Dormant
            # today: _check_and_publish above always resolves `ok=False`
            # (auto-send held), so this rarely fires yet -- wired now so it
            # activates automatically the moment publishing is enabled.
            try:
                from src.services.analytics.prediction import repredict_and_link_on_publish
                repredict_and_link_on_publish(post_id, channel_ref)
            except Exception:
                logger.exception("[publishing] prediction hook failed for post #%s", post_id)
        return {"ok": ok, "status": status, "note": full_note}

    async def _check_and_publish(self, post_id: int, channel_ref: str, confirm: bool):
        from telethon import TelegramClient
        from telethon.tl.functions.channels import GetParticipantRequest

        # Gate 1 — auto-send goes to the ONE explicitly configured PUBLISH_CHANNEL and
        # nowhere else. Unset => hold everything. This is what stops a channel from
        # starting to receive posts as a side effect of some other config change (e.g.
        # granting the account admin rights on the real channel for stats collection).
        target = self.settings.publish_channel
        if not target:
            return False, ("Auto-send held: no PUBLISH_CHANNEL configured. Set it to the "
                           "channel that should actually receive posts.")
        if channel_ref.lstrip("@").lower() != target.lstrip("@").lower():
            return False, (f"Auto-send refused: {channel_ref} is not the configured "
                           f"PUBLISH_CHANNEL ({target}).")

        with session_scope() as s:
            post = s.get(GeneratedPost, post_id)
            if post is None:
                return False, f"No generated post #{post_id}."
            text = post.rendered_text
        if not (text or "").strip():
            return False, f"Post #{post_id} has no rendered text — nothing to send."

        client = TelegramClient(self.settings.telegram_session_name,
                                self.settings.telegram_api_id, self.settings.telegram_api_hash)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return False, "Telegram session not authorised (run telegram-login)."
            entity = await resolve_entity(client, channel_ref)
            me = await client.get_me()
            # Gate 2 — verify admin post rights; never post without them.
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
            # link_preview=False: every post carries a shortened grbn.in link and Telegram's
            # auto-preview card for it is bulky/unwanted (dev_send.py does the same).
            msg = await client.send_message(entity, text, link_preview=False)
            return True, f"Sent to {channel_ref} (message id={msg.id})."
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
