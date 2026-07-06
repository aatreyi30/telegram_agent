"""Admin-only broadcast statistics collector (dormant until the account is admin).

Telegram's rich channel Statistics (subscriber growth, views/shares per post,
notification-enabled %, time-series graphs) are available ONLY to channel admins,
via ``stats.GetBroadcastStats``. Our account is a member, so this collector SKIPS
with a clear reason. The moment the account is granted admin (``can_view_stats``
flips True on collection), it activates automatically and populates
``channel_stat_snapshots`` — unlocking the subscriber-growth graphs the dashboard
currently labels as unavailable.

Nothing is fabricated while dormant: no snapshot is written, and the skip reason is
explicit.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from src.services.collection.base import BaseCollector, CollectorResult
from src.config.settings import get_settings
from src.db.models import Channel, ChannelStatSnapshot
from src.db.session import session_scope
from src.logger import get_logger

logger = get_logger(__name__)


class ChannelStatsCollector(BaseCollector):
    name = "channel_stats"
    retryable = True

    def __init__(self, channel_username: str):
        self.channel_username = channel_username.lstrip("@")
        self.settings = get_settings()

    def run(self, job) -> CollectorResult:
        result = CollectorResult()
        if not (self.settings.telegram_api_id and self.settings.telegram_api_hash):
            result.skipped_reason = "Telegram MTProto not configured."
            return result
        try:
            captured = asyncio.run(self._collect())
        except Exception as e:  # pragma: no cover - network/telethon paths
            result.skipped_reason = f"Stats fetch error: {type(e).__name__}: {e}"
            return result
        if captured is None:
            result.skipped_reason = (
                "Channel statistics are admin-only and this account is a member "
                "(can_view_stats=False). Grant the account admin rights to unlock "
                "subscriber-growth and reach stats — this collector then activates "
                "automatically.")
            return result
        result.added = 1
        return result

    async def _collect(self) -> bool | None:
        from telethon import TelegramClient
        from telethon.tl.functions.stats import GetBroadcastStatsRequest

        client = TelegramClient(self.settings.telegram_session_name,
                                self.settings.telegram_api_id, self.settings.telegram_api_hash)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return None
            entity = await client.get_entity(self.channel_username)
            try:
                stats = await client(GetBroadcastStatsRequest(channel=entity))
            except Exception:
                # Telegram rejects the request for non-admins -> dormant
                return None
            self._store(entity, stats)
            return True
        finally:
            await client.disconnect()

    def _store(self, entity, stats) -> None:  # pragma: no cover - needs admin data
        def _val(x):
            return getattr(getattr(stats, x, None), "current", None)

        with session_scope() as s:
            ch = s.scalar(select(Channel).where(Channel.username == self.channel_username))
            if ch is None:
                return
            ch.can_view_stats = True
            s.add(ChannelStatSnapshot(
                channel_id=ch.id, captured_at=datetime.now(timezone.utc),
                followers=_val("followers"),
                views_per_post=_val("views_per_post"),
                shares_per_post=_val("shares_per_post"),
                enabled_notifications_pct=getattr(
                    getattr(stats, "enabled_notifications", None), "part", None),
                graphs_json={"note": "broadcast stats captured; graph tokens omitted"},
            ))
