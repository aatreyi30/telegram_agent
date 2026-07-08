# be/src/services/analytics/daily_report.py
"""Deterministic day-wise aggregator — persists DailyChannelReport rows.

Owned reports are computed directly from Post rows for the IST day. day.py's
summarize() is reused for composition context, but the numeric spine here is
independent and exact so it is testable and stable.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from statistics import fmean, median

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Channel, Post
from src.db.models_report import DailyChannelReport, REPORT_VERSION, ReportSourceType
from src.services.analytics.periods import IST


def _ist_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=IST)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def _owned_channel(s: Session) -> Channel | None:
    return s.scalars(
        select(Channel).where(Channel.kind == "owned").order_by(Channel.participants_count.desc())
    ).first() or s.scalars(select(Channel)).first()


def build_owned_report(s: Session, day: date, channel_id: int | None = None) -> DailyChannelReport:
    start, end = _ist_bounds(day)
    ch = None
    if channel_id is None:
        ch = _owned_channel(s)
        channel_id = ch.id if ch else None
    q = select(Post).where(Post.posted_at >= start, Post.posted_at < end)
    if channel_id is not None:
        q = q.where(Post.channel_id == channel_id)
    posts = list(s.scalars(q))

    views = [p.views or 0 for p in posts]
    reactions = sum(p.reactions_total or 0 for p in posts)
    forwards = sum(p.forwards or 0 for p in posts)
    views_total = sum(views)
    top = max(posts, key=lambda p: p.views or 0, default=None)
    bottom = min(posts, key=lambda p: p.views or 0, default=None)
    hours = Counter(
        str((p.posted_at if p.posted_at.tzinfo else p.posted_at.replace(tzinfo=timezone.utc))
            .astimezone(IST).hour)
        for p in posts if p.posted_at)

    rep = DailyChannelReport(
        channel_id=channel_id, source_type=ReportSourceType.OWNED,
        report_date=day, report_version=REPORT_VERSION,
        posts_count=len(posts),
        deals_posted=sum(1 for p in posts if (p.text or "").strip()),
        merchants_featured=0,  # refined below from summarize() when available
        views_total=views_total,
        views_avg=round(fmean(views), 2) if views else 0.0,
        views_median=round(median(views), 2) if views else 0.0,
        views_max=max(views) if views else 0,
        views_min=min(views) if views else 0,
        top_post_id=(top.tg_message_id if top else None),
        bottom_post_id=(bottom.tg_message_id if bottom else None),
        reactions_total=reactions, forwards_total=forwards,
        engagement_rate=round((reactions + forwards) / views_total, 4) if views_total else 0.0,
        posting_hours=dict(hours),
        computed_at=datetime.now(timezone.utc),
        data_completeness=1.0,
    )
    # enrich composition + subs + merchants from summarize()/snapshots (best-effort)
    try:
        from src.services.analytics.day import summarize
        summ = summarize(s, day)
        if summ.get("available"):
            rep.type_mix = {t: c for t, c in summ.get("type_mix", [])}
            rep.category_mix = {m: c for m, c in summ.get("merchant_mix", [])}
            rep.merchants_featured = len(summ.get("merchants", []))
            merchants = summ.get("merchants", [])
            if merchants:
                rep.best_category = max(merchants, key=lambda m: m.get("total_views", 0))["key"]
                rep.worst_category = min(merchants, key=lambda m: m.get("total_views", 0))["key"]
    except Exception:
        pass
    _fill_subs(s, rep, channel_id, day)
    return rep


def _fill_subs(s: Session, rep: DailyChannelReport, channel_id: int | None, day: date) -> None:
    """subs_start/end/net from ParticipantSnapshot when present; else NULL.

    The real subscriber time-series lives in `participant_snapshots.count`
    (ParticipantSnapshot, captured every collection cycle). ChannelStatSnapshot
    requires admin `can_view_stats` and is empty in practice, so we read
    participant snapshots instead.
    """
    try:
        from src.db.models_growth_snapshot import ParticipantSnapshot
        start, end = _ist_bounds(day)
        snaps = list(s.scalars(
            select(ParticipantSnapshot)
            .where(ParticipantSnapshot.channel_id == channel_id,
                   ParticipantSnapshot.captured_at >= start,
                   ParticipantSnapshot.captured_at < end)
            .order_by(ParticipantSnapshot.captured_at)
        ))
        if snaps:
            rep.subs_start = snaps[0].count
            rep.subs_end = snaps[-1].count
            rep.subs_net = (rep.subs_end or 0) - (rep.subs_start or 0)
    except Exception:
        pass


def persist_report(s: Session, report: DailyChannelReport) -> DailyChannelReport:
    existing = s.scalars(
        select(DailyChannelReport).where(
            DailyChannelReport.channel_id == report.channel_id,
            DailyChannelReport.report_date == report.report_date,
            DailyChannelReport.source_type == report.source_type,
        )
    ).first()
    if existing is None:
        s.add(report)
        s.flush()
        return report
    for col in report.__table__.columns.keys():
        # id/created_at/updated_at are ORM/DB-managed (TimestampMixin: server_default +
        # onupdate); `report` here is an unpersisted transient instance whose updated_at
        # is still None, so blindly copying it would violate the NOT NULL constraint.
        # channel_id/report_date/source_type are the upsert key — never overwritten.
        if col in ("id", "created_at", "updated_at", "channel_id", "report_date", "source_type"):
            continue
        setattr(existing, col, getattr(report, col))
    s.flush()
    return existing


def run_daily_reports(s: Session, day: date | None = None) -> dict:
    if day is None:
        from src.services.analytics.day import latest_owned_date
        day = latest_owned_date(s)
    if day is None:
        return {"owned": 0, "competitor": 0, "date": None}
    persist_report(s, build_owned_report(s, day))
    comp = _build_competitor_reports(s, day)
    return {"owned": 1, "competitor": comp, "date": day.isoformat()}


def _build_competitor_reports(s: Session, day: date) -> int:
    """Per-competitor daily reports from CompetitorPost cumulative views.
    Shallower than owned (no forwards/reactions guaranteed); data_completeness < 1."""
    from src.db.models import Competitor, CompetitorPost
    start, end = _ist_bounds(day)
    n = 0
    for c in s.scalars(select(Competitor)):
        posts = list(s.scalars(
            select(CompetitorPost).where(
                CompetitorPost.competitor_id == c.id,
                CompetitorPost.posted_at >= start,
                CompetitorPost.posted_at < end,
            )
        ))
        if not posts:
            continue
        views = [p.views or 0 for p in posts]
        rep = DailyChannelReport(
            channel_id=None, source_type=ReportSourceType.COMPETITOR,
            report_date=day, report_version=REPORT_VERSION,
            posts_count=len(posts), deals_posted=len(posts), merchants_featured=0,
            views_total=sum(views),
            views_avg=round(fmean(views), 2) if views else 0.0,
            views_median=round(median(views), 2) if views else 0.0,
            views_max=max(views) if views else 0, views_min=min(views) if views else 0,
            reactions_total=0, forwards_total=0, engagement_rate=0.0,
            computed_at=datetime.now(timezone.utc), data_completeness=0.6,
        )
        # store competitor identity in category_mix so reports stay keyable without a channel row
        rep.category_mix = {"_competitor": c.username or str(c.id)}
        persist_report(s, rep)
        n += 1
    return n
