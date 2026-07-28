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
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from src.config.settings import get_settings
from src.db.models_generation import GeneratedPost, PostStatus
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus
from src.logger import get_logger

logger = get_logger(__name__)


def _write_with_retry(fn, *, attempts: int = 5, base_delay: float = 0.4) -> None:
    """Run a tiny single-row write, retrying on SQLite 'database is locked'. The
    post-send status / message-id writes MUST NOT be lost to a transient lock — a lost
    status write is exactly what left a SENT post marked 'failed' and triggered a
    re-send. Every write here is an idempotent single-row update, so retrying is always
    safe. Non-lock errors, or a lock that survives every attempt, still raise."""
    for i in range(attempts):
        try:
            with session_scope() as s:
                fn(s)
            return
        except OperationalError as e:
            if "database is locked" not in str(e).lower() or i == attempts - 1:
                raise
            logger.warning("[publishing] DB locked on a status write — retry %d/%d", i + 1, attempts)
            time.sleep(base_delay * (i + 1))


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
        from src.services.generation.revalidate import revalidate_each

        stale_min = self.settings.prepublish_max_staleness_min
        deal_ids = list(post.deal_ids or [])
        verdicts = revalidate_each(deal_ids, max_staleness_min=stale_min)
        failed = {d: v["reason"] for d, v in verdicts.items() if not v["ok"]}
        trim_note = ""
        if failed:
            # A loot board is ONE message carrying ~10 deals. Killing the whole message
            # because item #7 sold out threw away nine live deals — so drop the dead
            # items and send the rest, as long as enough of the board survives.
            trimmed = self._trim_failed_deals(post, set(failed)) if len(deal_ids) > 1 else None
            floor = self.settings.min_collection_items
            if trimmed is None or len(trimmed[1]) < floor:
                reason = next(iter(failed.values()))
                if trimmed is not None:
                    reason = (f"only {len(trimmed[1])} of {len(deal_ids)} deals survived "
                              f"(need {floor}); first failure: {reason}")
                note = f"blocked_stale: {reason}"
                self._set(post_id, PostStatus.BLOCKED, note)
                # notification_engine already flags BLOCKED posts; nothing else needed
                return {"ok": False, "status": PostStatus.BLOCKED, "note": note}
            text, survivors = trimmed
            # Persist BEFORE sending: _check_and_publish re-reads rendered_text from the
            # DB, so the trimmed text is what actually goes out, and what we recorded is
            # what the channel received.
            with session_scope() as s:
                row = s.get(GeneratedPost, post_id)
                row.rendered_text = text
                row.deal_ids = survivors
            dropped = ", ".join(f"{d} ({r})" for d, r in failed.items())
            trim_note = (f"Dropped {len(failed)} of {len(deal_ids)} deals at publish time: "
                         f"{dropped}.")
            logger.info("[publishing] post #%s trimmed to %d deals — %s",
                        post_id, len(survivors), dropped)

        ok, reason = asyncio.run(self._check_and_publish(post_id, channel_ref, confirm=True))
        status = PostStatus.PUBLISHED if ok else PostStatus.BLOCKED
        full_note = " ".join(p for p in (aff_note, trim_note, reason) if p).strip()
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

    @staticmethod
    def _trim_failed_deals(post: GeneratedPost, failed_ids: set[str]):
        """Rebuild a board's text without the deals that failed revalidation.

        Returns ``(new_text, surviving_deal_ids)``, or ``None`` when the post cannot be
        trimmed safely — in which case the caller blocks the whole post, i.e. the old
        all-or-nothing behaviour. We refuse rather than guess in two cases:

        * no per-item line map in ``format_meta`` — posts rendered before the formatter
          started recording one, and single-deal posts, which have no items to drop;
        * a mapped line is not found verbatim in ``rendered_text`` — the text was edited
          after rendering, so deleting by substring could mangle a neighbouring deal.

        Matching is on the recorded line, never on the deal's URL: with an affiliate
        provider configured the rendered link is a shortened one that no longer contains
        the product URL, and a URL-substring match would silently stop working.
        """
        items = ((post.format_meta or {}).get("items")) or []
        if not items:
            return None
        text = post.rendered_text or ""
        survivors: list[str] = []
        for item in items:
            deal_id, line = item.get("deal_id"), (item.get("line") or "").strip()
            if deal_id not in failed_ids:
                survivors.append(deal_id)
                continue
            if not line or line not in text:
                return None
            text = text.replace(line + "\n", "", 1) if line + "\n" in text \
                else text.replace(line, "", 1)
        return text.strip(), survivors

    async def _check_and_publish(self, post_id: int, channel_ref: str, confirm: bool):
        from telethon.tl.functions.channels import GetParticipantRequest
        from src.shared.telegram import telegram_session

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
            already_sent = post.telegram_message_id
        # IDEMPOTENCY: if a prior attempt already sent this post (its Telegram message id
        # is recorded) but the status write was lost to a DB lock, do NOT send again —
        # report success so the scheduler reconciles it to published. This is the guard
        # that stops a retry from double-posting a message that already went out.
        if already_sent is not None:
            return True, (f"Already sent (message id={already_sent}) on a prior attempt; "
                          "not resending.")
        if not (text or "").strip():
            return False, f"Post #{post_id} has no rendered text — nothing to send."

        async with telegram_session(self.settings) as client:
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
            # Record the message id in its OWN resilient write, IMMEDIATELY after the send
            # and BEFORE the status write below — so even if everything after this is lost
            # to a DB lock, the next attempt sees the post already went out and won't
            # re-send it. This is the durable half of the double-post guard.
            self._record_message_id(post_id, msg.id)
            return True, f"Sent to {channel_ref} (message id={msg.id})."

    @staticmethod
    def _record_message_id(post_id: int, message_id: int) -> None:
        """Persist the Telegram message id of a successful send (resiliently, and only if
        not already set — never overwrite an earlier send's id)."""
        def _apply(s):
            post = s.get(GeneratedPost, post_id)
            if post is not None and post.telegram_message_id is None:
                post.telegram_message_id = message_id
        _write_with_retry(_apply)

    @staticmethod
    def _set(post_id: int, status: str, note: str, channel_ref: str | None = None) -> None:
        def _apply(s):
            post = s.get(GeneratedPost, post_id)
            if post is None:
                return
            post.status = status
            post.publish_note = note
            if channel_ref:
                post.channel_ref = channel_ref
        _write_with_retry(_apply)
