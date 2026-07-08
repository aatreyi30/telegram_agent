"""Owned-channel collector (MTProto via Telethon).

Collects first-party data the operator is entitled to: full message history
(target up to 12 months), current view/forward/reaction counters, and — where
the channel is large enough for ``can_view_stats`` — broadcast statistics.

Three collection modes (spec 08):
  * INITIAL      — historical backfill (long-running, resumable, idempotent)
  * INCREMENTAL  — only messages newer than the stored cursor
  * ANALYTICS    — broadcast stats snapshot + refresh recent-post counters
                   (the latter reconstructs view velocity, which Telegram does
                   NOT provide retroactively — Data Validation Matrix Feature 7)

Nothing is fabricated: missing counters stay NULL, and if the account is not
authorised the collector reports SKIPPED rather than failing.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from src.services.collection.base import BaseCollector, CollectorResult
from src.services.collection.raw_store import store_raw
from src.services.collection.util import content_hash, extract_urls, to_utc
from src.config.settings import get_settings
from src.db.models import (
    Channel,
    CollectionType,
    Post,
    PostMetricSnapshot,
)
from src.db.models_growth_snapshot import DailySubscriberStat, ParticipantSnapshot
from src.db.session import session_scope
from src.services.analytics.periods import IST
from src.services.events import Event, EventType, get_event_bus
from src.logger import get_logger

logger = get_logger(__name__)

HISTORY_WINDOW_DAYS = 365
# Refresh counters for posts published within this window during ANALYTICS runs.
METRIC_REFRESH_WINDOW_DAYS = 30


def _upsert_daily_subscriber_stat(s, channel_id: int, day, count: int, updated_at: datetime) -> None:
    """Incrementally roll a fresh participant count into today's (IST) daily
    subscriber-stat row: first observation of the day seeds start/end, later
    observations turn the delta since the row's last-seen count into joined/left.

    Must be called in the same session/transaction as the ParticipantSnapshot
    insert it accompanies so a mid-cycle failure leaves both untouched.
    """
    row = s.scalar(
        select(DailySubscriberStat).where(
            DailySubscriberStat.channel_id == channel_id,
            DailySubscriberStat.stat_date == day,
        )
    )
    if row is None:
        s.add(
            DailySubscriberStat(
                channel_id=channel_id,
                stat_date=day,
                subs_start=count,
                subs_end=count,
                subs_joined=0,
                subs_left=0,
                subs_net=0,
                updated_at=updated_at,
            )
        )
        return
    delta = count - row.subs_end
    if delta > 0:
        row.subs_joined += delta
    elif delta < 0:
        row.subs_left += abs(delta)
    row.subs_end = count
    row.subs_net = row.subs_end - row.subs_start
    row.updated_at = updated_at


class OwnedChannelCollector(BaseCollector):
    name = "telegram_owned"

    def __init__(self, channel_ref: str, collection_type: str = CollectionType.INCREMENTAL):
        self.channel_ref = channel_ref
        self.collection_type = collection_type
        self.settings = get_settings()
        self.bus = get_event_bus()

    def available(self) -> tuple[bool, str | None]:
        # The channel is supplied per-collector (arg or scheduler), so only the
        # API credentials + an authorised session are required here.
        if not (self.settings.telegram_api_id and self.settings.telegram_api_hash):
            return (
                False,
                "Telegram MTProto not configured (TELEGRAM_API_ID / API_HASH missing).",
            )
        if not self.channel_ref:
            return False, "No channel specified."
        return True, None

    def run(self, job) -> CollectorResult:
        # Telethon is async; run its own loop within this worker thread.
        return asyncio.run(self._run_async(job.id))

    # ------------------------------------------------------------------ #
    async def _run_async(self, job_id: int) -> CollectorResult:
        from telethon import TelegramClient
        from telethon.tl.functions.channels import GetFullChannelRequest

        client = TelegramClient(
            self.settings.telegram_session_name,
            self.settings.telegram_api_id,
            self.settings.telegram_api_hash,
        )
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return CollectorResult(
                    skipped_reason=(
                        "Telegram session is not authorised. Run "
                        "`tgagent telegram-login` once to authenticate."
                    )
                )
            entity = await client.get_entity(self._normalize_ref(self.channel_ref))
            full = await client(GetFullChannelRequest(channel=entity))
            channel_row_id = self._upsert_channel(entity, full, job_id)

            if self.collection_type == CollectionType.ANALYTICS:
                return await self._collect_analytics(
                    client, entity, full, channel_row_id, job_id
                )
            return await self._collect_messages(client, entity, channel_row_id, job_id)
        finally:
            await client.disconnect()

    # ------------------------------------------------------------------ #
    async def _collect_messages(self, client, entity, channel_row_id, job_id) -> CollectorResult:
        result = CollectorResult()
        with session_scope() as s:
            ch = s.get(Channel, channel_row_id)
            cursor = ch.last_message_id or 0
            initial = ch.first_collected_at is None or self.collection_type == CollectionType.INITIAL

        cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_WINDOW_DAYS)
        max_seen_id = cursor
        # INITIAL: walk history back to the 12-month cutoff.
        # INCREMENTAL: only messages with id > stored cursor.
        iter_kwargs = {} if initial else {"min_id": cursor}

        async for msg in client.iter_messages(entity, **iter_kwargs):
            if getattr(msg, "date", None) and to_utc(msg.date) < cutoff and initial:
                break
            if msg.id <= cursor and not initial:
                continue
            added, updated = self._store_post(channel_row_id, msg, job_id)
            result.processed += 1
            result.added += added
            result.updated += updated
            max_seen_id = max(max_seen_id, msg.id)

        # advance cursor + mark timestamps
        with session_scope() as s:
            ch = s.get(Channel, channel_row_id)
            now = datetime.now(timezone.utc)
            if ch.first_collected_at is None:
                ch.first_collected_at = now
            ch.last_collected_at = now
            if max_seen_id and max_seen_id > (ch.last_message_id or 0):
                ch.last_message_id = max_seen_id
        return result

    def _store_post(self, channel_row_id: int, msg, job_id: int) -> tuple[int, int]:
        # Events are emitted AFTER commit (below), never inside the session —
        # nested write sessions deadlock on SQLite.
        text = msg.message or None
        links = extract_urls(text)
        media_type = type(msg.media).__name__ if msg.media else None
        digest = content_hash(text, links, media_type)
        reactions_total = self._sum_reactions(msg)
        emit: tuple[str, int] | None = None  # (event_type, post_id)
        added = updated = 0

        with session_scope() as s:
            snap = store_raw(
                s,
                source=self.name,
                source_ref=f"{self.channel_ref}:{msg.id}",
                payload=self._msg_to_dict(msg),
                job_id=job_id,
            )
            existing = s.scalar(
                select(Post).where(
                    Post.channel_id == channel_row_id, Post.tg_message_id == msg.id
                )
            )
            now = datetime.now(timezone.utc)
            if existing is None:
                post = Post(
                    channel_id=channel_row_id,
                    tg_message_id=msg.id,
                    posted_at=to_utc(getattr(msg, "date", None)),
                    edited_at=to_utc(getattr(msg, "edit_date", None)),
                    text=text,
                    content_sha256=digest,
                    has_media=bool(msg.media),
                    media_type=media_type,
                    links=links or None,
                    grouped_id=getattr(msg, "grouped_id", None),
                    views=getattr(msg, "views", None),
                    forwards=getattr(msg, "forwards", None),
                    reactions_total=reactions_total,
                    raw_snapshot_id=snap.id,
                    collected_at=now,
                )
                s.add(post)
                s.flush()
                self._record_metric(s, post.id, msg, reactions_total)
                emit = (EventType.POST_COLLECTED, post.id)
                added = 1
            else:
                changed = existing.content_sha256 != digest or existing.edited_at != to_utc(
                    getattr(msg, "edit_date", None)
                )
                existing.views = getattr(msg, "views", None)
                existing.forwards = getattr(msg, "forwards", None)
                existing.reactions_total = reactions_total
                if changed:
                    existing.text = text
                    existing.content_sha256 = digest
                    existing.links = links or None
                    existing.edited_at = to_utc(getattr(msg, "edit_date", None))
                    existing.raw_snapshot_id = snap.id
                    emit = (EventType.POST_UPDATED, existing.id)
                    updated = 1
                self._record_metric(s, existing.id, msg, reactions_total)

        if emit is not None:
            self._emit(emit[0], "post", emit[1], job_id, {"tg_message_id": msg.id})
        return added, updated

    # ------------------------------------------------------------------ #
    async def _collect_analytics(self, client, entity, full, channel_row_id, job_id) -> CollectorResult:
        result = CollectorResult()
        # (b) refresh counters for recent posts (view-velocity reconstruction)
        with session_scope() as s:
            cutoff = datetime.now(timezone.utc) - timedelta(days=METRIC_REFRESH_WINDOW_DAYS)
            recent = s.scalars(
                select(Post).where(
                    Post.channel_id == channel_row_id,
                    Post.posted_at >= cutoff,
                    Post.is_deleted.is_(False),
                )
            ).all()
            recent_ids = [(p.id, p.tg_message_id) for p in recent]

        if recent_ids:
            msg_ids = [mid for _, mid in recent_ids]
            fresh = await client.get_messages(entity, ids=msg_ids)
            by_msg = {m.id: m for m in fresh if m is not None}
            with session_scope() as s:
                for post_id, tg_id in recent_ids:
                    msg = by_msg.get(tg_id)
                    if msg is None:
                        continue
                    reactions_total = self._sum_reactions(msg)
                    post = s.get(Post, post_id)
                    post.views = getattr(msg, "views", None)
                    post.forwards = getattr(msg, "forwards", None)
                    post.reactions_total = reactions_total
                    self._record_metric(s, post_id, msg, reactions_total)
                    result.processed += 1
                    result.updated += 1
            self._emit(EventType.POST_METRICS_UPDATED, "channel", channel_row_id, job_id,
                       {"posts_refreshed": len(recent_ids)})
        return result

    # ------------------------------------------------------------------ #
    def _upsert_channel(self, entity, full, job_id) -> int:
        full_chat = full.full_chat
        with session_scope() as s:
            row = s.scalar(select(Channel).where(Channel.tg_channel_id == entity.id))
            now = datetime.now(timezone.utc)
            if row is None:
                # adopt a pending row added via the UI (negative placeholder id, matched
                # by @username) so it isn't duplicated once Telegram resolves the real id.
                uname = getattr(entity, "username", None)
                if uname:
                    row = s.scalar(select(Channel).where(
                        func.lower(Channel.username) == uname.lower(),
                        Channel.tg_channel_id < 0))
                if row is not None:
                    row.tg_channel_id = entity.id
                else:
                    row = Channel(tg_channel_id=entity.id)
                    s.add(row)
            row.status = "active"
            row.username = getattr(entity, "username", None)
            row.title = getattr(entity, "title", None)
            row.description = getattr(full_chat, "about", None)
            pc = getattr(full_chat, "participants_count", None)
            row.participants_count = pc
            row.can_view_stats = bool(getattr(full_chat, "can_view_stats", False))
            if pc is not None:
                s.add(ParticipantSnapshot(channel_id=row.id, captured_at=now, count=pc))
                _upsert_daily_subscriber_stat(s, row.id, now.astimezone(IST).date(), pc, now)
            row.stats_dc = getattr(full_chat, "stats_dc", None)
            s.flush()
            row_id = row.id
        self._emit(EventType.CHANNEL_UPDATED, "channel", row_id, job_id, {})
        return row_id

    @staticmethod
    def _record_metric(session, post_id: int, msg, reactions_total) -> None:
        posted_at = to_utc(getattr(msg, "date", None))
        now = datetime.now(timezone.utc)
        age_hours = ((now - posted_at).total_seconds() / 3600.0) if posted_at else None
        session.add(
            PostMetricSnapshot(
                post_id=post_id,
                captured_at=now,
                age_hours=age_hours,
                views=getattr(msg, "views", None),
                forwards=getattr(msg, "forwards", None),
                reactions_total=reactions_total,
                reactions_breakdown=OwnedChannelCollector._reactions_breakdown(msg),
            )
        )

    @staticmethod
    def _sum_reactions(msg) -> int | None:
        reactions = getattr(msg, "reactions", None)
        if not reactions or not getattr(reactions, "results", None):
            return None
        return sum(getattr(r, "count", 0) for r in reactions.results)

    @staticmethod
    def _reactions_breakdown(msg) -> dict | None:
        reactions = getattr(msg, "reactions", None)
        if not reactions or not getattr(reactions, "results", None):
            return None
        out: dict[str, int] = {}
        for r in reactions.results:
            emoticon = getattr(getattr(r, "reaction", None), "emoticon", None) or "custom"
            out[emoticon] = out.get(emoticon, 0) + getattr(r, "count", 0)
        return out or None

    @staticmethod
    def _msg_to_dict(msg) -> dict:
        return {
            "id": msg.id,
            "date": str(getattr(msg, "date", None)),
            "edit_date": str(getattr(msg, "edit_date", None)),
            "message": msg.message,
            "views": getattr(msg, "views", None),
            "forwards": getattr(msg, "forwards", None),
            "grouped_id": getattr(msg, "grouped_id", None),
            "has_media": bool(msg.media),
            "media_type": type(msg.media).__name__ if msg.media else None,
        }

    @staticmethod
    def _normalize_ref(ref: str):
        ref = ref.strip()
        if ref.lstrip("-").isdigit():
            return int(ref)
        return ref.lstrip("@")

    def _emit(self, event_type, entity_type, entity_id, job_id, data) -> None:
        self.bus.publish(
            Event(
                event_type=event_type,
                entity_type=entity_type,
                entity_id=str(entity_id),
                data=data,
                job_id=job_id,
            )
        )
