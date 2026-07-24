"""DEV-ONLY: send a real Telegram message via the operator's own logged-in session,
straight to a chat/group/channel they choose (e.g. a personal test group).

This intentionally bypasses ``publishing.Publisher`` entirely — no admin-rights check,
no revalidation, no affiliate-link gate, no sign-off. It is not wired into any
scheduler, router, or the real publish path. Use only against a private test chat you
control; never point it at the production owned channel.
"""

from __future__ import annotations

import asyncio

from src.config.settings import get_settings


# The chat-ref resolver lives with the Publisher (both need the private-channel dialog
# scan); importing the helper does NOT route this module through the Publisher's gates.
from src.services.generation.publishing import resolve_entity as _resolve_entity


async def _send(chat_ref: str, text: str) -> str:
    from telethon import TelegramClient

    settings = get_settings()
    if not (settings.telegram_api_id and settings.telegram_api_hash):
        raise RuntimeError("Telegram MTProto not configured (TELEGRAM_API_ID / TELEGRAM_API_HASH).")
    client = TelegramClient(settings.telegram_session_name,
                             settings.telegram_api_id, settings.telegram_api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session not authorised — run `tgagent telegram-login` first.")
        entity = await _resolve_entity(client, chat_ref)
        msg = await client.send_message(entity, text, link_preview=False)
        return f"sent message id={msg.id} to {chat_ref!r}"
    finally:
        await client.disconnect()


def dev_send(chat_ref: str, text: str) -> str:
    return asyncio.run(_send(chat_ref, text))


async def _list_chats(limit: int) -> list[dict]:
    from telethon import TelegramClient

    settings = get_settings()
    if not (settings.telegram_api_id and settings.telegram_api_hash):
        raise RuntimeError("Telegram MTProto not configured (TELEGRAM_API_ID / TELEGRAM_API_HASH).")
    client = TelegramClient(settings.telegram_session_name,
                             settings.telegram_api_id, settings.telegram_api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session not authorised — run `tgagent telegram-login` first.")
        rows = []
        async for d in client.iter_dialogs(limit=limit):
            e = d.entity
            kind = "user" if d.is_user else "group" if d.is_group else "channel"
            username = getattr(e, "username", None)
            rows.append({
                "name": d.name, "kind": kind,
                "chat_ref": f"@{username}" if username else str(d.id),
                "id": d.id,
            })
        return rows
    finally:
        await client.disconnect()


def list_chats(limit: int = 30) -> list[dict]:
    return asyncio.run(_list_chats(limit))


# Telegram caps a photo CAPTION at 1024 chars; a text message allows 4096. Deal posts
# sit well under 1024, but if one doesn't we skip the image rather than truncate the copy.
_CAPTION_LIMIT = 1024


def _draft_image(post) -> str | None:
    """The image URL jit_fill stashed on this draft, if any. jit_fill (§8b) only stashes
    one for the ~5 slots/day picked as the image budget — every other draft has none in
    its meta even when the underlying deal has a photo, which is what keeps the whole
    day's mix at ~5 image posts instead of "every deal with an image"."""
    return (post.format_meta or {}).get("image_url")


async def _publish_drafts(draft_ids: list[int], chat_ref: str, pace_seconds: float,
                          with_images: bool = True) -> list[dict]:
    from telethon import TelegramClient

    from src.db.models_generation import GeneratedPost
    from src.db.session import session_scope

    settings = get_settings()
    if not (settings.telegram_api_id and settings.telegram_api_hash):
        raise RuntimeError("Telegram MTProto not configured (TELEGRAM_API_ID / TELEGRAM_API_HASH).")
    client = TelegramClient(settings.telegram_session_name,
                             settings.telegram_api_id, settings.telegram_api_hash)
    await client.connect()
    results: list[dict] = []
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session not authorised — run `tgagent telegram-login` first.")
        entity = await _resolve_entity(client, chat_ref)
        for i, draft_id in enumerate(draft_ids):
            with session_scope() as s:
                post = s.get(GeneratedPost, draft_id)
                if post is None:
                    results.append({"draft_id": draft_id, "ok": False, "note": "not found"})
                    continue
                text = post.rendered_text
                image = _draft_image(post) if with_images else None
            sent_with_image = False
            try:
                if image and len(text or "") <= _CAPTION_LIMIT:
                    # Telethon takes the URL directly — it downloads then re-uploads as a
                    # photo with the post text as caption. Falls back to text on any failure
                    # (dead URL / unsupported format) so a bad image never drops the post.
                    try:
                        msg = await client.send_file(entity, image, caption=text)
                        sent_with_image = True
                    except Exception:  # noqa: BLE001 — degrade to text, keep the post
                        msg = await client.send_message(entity, text, link_preview=False)
                else:
                    msg = await client.send_message(entity, text, link_preview=False)
            except Exception as e:  # noqa: BLE001 — one bad draft must not abort the rest
                results.append({"draft_id": draft_id, "ok": False, "note": str(e)})
                continue
            kind = "photo" if sent_with_image else "text"
            note = f"dev-sent ({kind}) to {chat_ref} (msg id={msg.id})"
            with session_scope() as s:
                post = s.get(GeneratedPost, draft_id)
                post.publish_note = note
                post.channel_ref = chat_ref
            results.append({"draft_id": draft_id, "ok": True, "note": note,
                            "message_id": msg.id, "image": sent_with_image})
            if i < len(draft_ids) - 1:
                await asyncio.sleep(pace_seconds)
        return results
    finally:
        await client.disconnect()


def publish_drafts(draft_ids: list[int], chat_ref: str, pace_seconds: float = 1.5,
                   with_images: bool = True) -> list[dict]:
    """DEV ONLY: send each draft's rendered_text to ``chat_ref``, paced. Attaches a photo
    (caption = post text) only for drafts jit_fill flagged as one of the day's ~5 image
    slots (§8b) and whose caption fits Telegram's 1024-char cap; every other draft, and
    any flagged draft whose image URL fails to send, goes text-only. Stamps
    publish_note/channel_ref for traceability but never touches status (not the real
    Publisher — must never read as PUBLISHED to the official channel)."""
    return asyncio.run(_publish_drafts(draft_ids, chat_ref, pace_seconds, with_images))


def drafts_for_day(day, include_already_sent: bool = False) -> list[int]:
    """IDs of jit_fill drafts (bucket "aislot:<plan_id>:...") for ``day``'s AI plan.
    Excludes already dev-sent drafts unless ``include_already_sent`` (idempotent re-run)."""
    from sqlalchemy import select

    from src.db.models_campaign import CampaignPlan, PlanType
    from src.db.models_generation import GeneratedPost
    from src.db.session import session_scope

    with session_scope() as s:
        plan_ids = s.scalars(
            select(CampaignPlan.id).where(
                CampaignPlan.plan_type == PlanType.DAILY,
                CampaignPlan.target_date == day,
                CampaignPlan.is_ai_generated == True,  # noqa: E712
            )
        ).all()
        if not plan_ids:
            return []
        rows = s.execute(
            select(GeneratedPost.id, GeneratedPost.selection_bucket, GeneratedPost.publish_note)
            .order_by(GeneratedPost.id)
        ).all()
        prefixes = tuple(f"aislot:{pid}:" for pid in plan_ids)
        out = []
        for gid, bucket, note in rows:
            if not bucket or not bucket.startswith(prefixes):
                continue
            if not include_already_sent and (note or "").startswith("dev-sent to"):
                continue
            out.append(gid)
        return out
