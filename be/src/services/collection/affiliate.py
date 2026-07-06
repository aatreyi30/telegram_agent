"""Affiliate link tracker (Phase 1, PARTIAL by data availability).

What IS buildable now (Data Validation Matrix Feature 14):
  * resolve short/affiliate URLs (follow redirects) -> final destination + domain
  * HTTP reachability check -> is_broken (broken-link detection)
  * extract tracking parameters present on the resolved URL (attribution tags)

What is NOT available (Revenue Data Gap, Matrix §5):
  * click counts and conversion/revenue per link — these live inside affiliate
    portals with no standard API. ``clicks`` stays NULL and is NEVER estimated.
    An operator may later supply portal data manually to populate it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
from sqlalchemy import select

from src.services.collection.base import BaseCollector, CollectorResult
from src.services.collection.merchants.registry import detect_merchant_key
from src.db.models import AffiliateLink, Merchant
from src.db.session import session_scope
from src.services.events import Event, EventType, get_event_bus


class AffiliateLinkCollector(BaseCollector):
    name = "affiliate_link"

    def __init__(self, short_url: str):
        self.short_url = short_url.strip()
        self.bus = get_event_bus()

    def run(self, job) -> CollectorResult:
        result = CollectorResult(processed=1)
        resolved_url: str | None = None
        status: int | None = None
        is_broken: bool | None = None

        try:
            with httpx.Client(
                timeout=20.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; TGIntelBot/1.0)"},
            ) as client:
                resp = client.get(self.short_url)
                resolved_url = str(resp.url)
                status = resp.status_code
                is_broken = status >= 400
        except httpx.HTTPError:
            is_broken = True  # unreachable == broken (observed fact, not a guess)

        domain = urlsplit(resolved_url).netloc if resolved_url else None
        params = (
            {k: v[0] for k, v in parse_qs(urlsplit(resolved_url).query).items()}
            if resolved_url
            else None
        )
        merchant_key = detect_merchant_key(resolved_url) if resolved_url else None

        with session_scope() as s:
            merchant_id = None
            if merchant_key:
                merchant = s.scalar(select(Merchant).where(Merchant.key == merchant_key))
                merchant_id = merchant.id if merchant else None

            link = s.scalar(
                select(AffiliateLink).where(AffiliateLink.short_url == self.short_url)
            )
            now = datetime.now(timezone.utc)
            if link is None:
                link = AffiliateLink(short_url=self.short_url)
                s.add(link)
                result.added += 1
            else:
                result.updated += 1
            link.resolved_url = resolved_url
            link.domain = domain
            link.merchant_id = merchant_id
            link.tracking_params = params
            link.http_status = status
            link.is_broken = is_broken
            # link.clicks intentionally left as-is (UNKNOWN unless manual input)
            link.last_checked_at = now
            s.flush()
            link_id = link.id

        self._emit(EventType.AFFILIATE_LINK_UPDATED, "affiliate_link", link_id, job.id,
                   {"is_broken": is_broken, "status": status})
        return result

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
