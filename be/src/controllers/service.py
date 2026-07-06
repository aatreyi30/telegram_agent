"""Read-only view-model builders for the dashboard.

Everything here is a plain DB read of the engines' STORED outputs — the same
verified data the AI layer is grounded on (reuses ai/context.py). No engine is
re-run and no LLM is called; the dashboard only presents what's already computed.
"""

from __future__ import annotations

from sqlalchemy import func, select

from src.ai import context as ctx
from src.config.settings import get_settings
from src.db.models import Channel, Competitor, Post
from src.db.models_automation import ScheduledPost, ScheduleStatus
from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan
from src.db.models_generation import GeneratedPost, PostStatus
from src.db.session import session_scope


def list_channels() -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(Channel).order_by(Channel.id)).all()
        post_counts = dict(s.execute(
            select(Post.channel_id, func.count()).group_by(Post.channel_id)).all())
        return [{"id": c.id, "username": c.username, "title": c.title, "kind": c.kind,
                 "org_id": c.org_id, "posts": post_counts.get(c.id, 0)} for c in rows]


def delete_channel(channel_id: int, confirm: bool = False) -> dict:
    """Delete a channel and all of its dependent data (posts, metrics, normalized
    rows, classifications, extracted facts). Destructive + irreversible, so a preview
    is returned unless confirm=True. Deletes in FK-dependency order via subqueries
    (no large IN-lists, so it's safe for channels with many posts)."""
    from src.db.models import ChannelStatSnapshot, PostMetricSnapshot
    from src.db.models_classification import PostClassification
    from src.db.models_normalization import (
        ExtractedCoupon, ExtractedLink, ExtractedPrice, NormalizedPost, SourceType)

    with session_scope() as s:
        ch = s.get(Channel, channel_id)
        if ch is None:
            return {"ok": False, "error": f"No channel #{channel_id}."}

        post_ids = select(Post.id).where(Post.channel_id == channel_id)
        norm_ids = select(NormalizedPost.id).where(
            NormalizedPost.source_type == SourceType.OWNED,
            NormalizedPost.source_id.in_(post_ids))

        def _count(model, *where):
            return s.scalar(select(func.count()).select_from(model).where(*where)) or 0

        counts = {
            "channel": ch.username or ch.title or str(channel_id),
            "posts": _count(Post, Post.channel_id == channel_id),
            "normalized_posts": _count(NormalizedPost, NormalizedPost.source_type == SourceType.OWNED,
                                       NormalizedPost.source_id.in_(post_ids)),
            "metric_snapshots": _count(PostMetricSnapshot, PostMetricSnapshot.post_id.in_(post_ids)),
        }
        if not confirm:
            return {"ok": False, "requires_confirm": True, "would_delete": counts,
                    "note": "This is irreversible. Re-send with confirm=true to proceed."}

        # delete children first, then parents (FK-safe)
        s.query(PostClassification).filter(
            PostClassification.normalized_post_id.in_(norm_ids)).delete(synchronize_session=False)
        for M in (ExtractedPrice, ExtractedCoupon, ExtractedLink):
            s.query(M).filter(M.normalized_post_id.in_(norm_ids)).delete(synchronize_session=False)
        s.query(NormalizedPost).filter(
            NormalizedPost.source_type == SourceType.OWNED,
            NormalizedPost.source_id.in_(post_ids)).delete(synchronize_session=False)
        s.query(PostMetricSnapshot).filter(
            PostMetricSnapshot.post_id.in_(post_ids)).delete(synchronize_session=False)
        s.query(ChannelStatSnapshot).filter(
            ChannelStatSnapshot.channel_id == channel_id).delete(synchronize_session=False)
        s.query(Post).filter(Post.channel_id == channel_id).delete(synchronize_session=False)
        s.delete(ch)
        return {"ok": True, "deleted": counts}


def org_channel_label() -> str:
    """'GrabOn · @GrabOnIndiaOfficial' for the header. Best-effort; never raises."""
    try:
        from src.db.models_org import Organization
        with session_scope() as s:
            org = s.scalars(select(Organization)).first()
            ch = s.scalars(select(Channel).where(Channel.kind == "owned")
                           .order_by(Channel.participants_count.desc())).first()
            org_name = org.name if org else "—"
            handle = f"@{ch.username}" if (ch and ch.username) else "no channel"
            return f"{org_name} · {handle}"
    except Exception:
        return ""


def overview() -> dict:
    """Headline counts + the publishing-gate status."""
    s_ = get_settings()
    with session_scope() as s:
        posts = s.scalar(select(func.count()).select_from(Post)) or 0
        competitors = s.scalar(select(func.count()).select_from(Competitor)) or 0
        drafts = s.scalar(select(func.count()).select_from(GeneratedPost)
                          .where(GeneratedPost.status == PostStatus.DRAFT)) or 0
        ch = ctx.channel_overview(s)
        queue_counts = dict(s.execute(
            select(ScheduledPost.status, func.count()).group_by(ScheduledPost.status)).all())
    return {
        "channel": ch,
        "posts": posts,
        "competitors": competitors,
        "drafts": drafts,
        "queue_counts": queue_counts,
        "affiliate_provider": s_.affiliate_provider_name,
        "publishing_gates": _publishing_gates(s_, queue_counts),
    }


def _publishing_gates(settings, queue_counts: dict) -> list[dict]:
    """Plain-language status of what still stands between drafts and a live post."""
    affiliate_closed = settings.affiliate_provider_name != "generic"
    blocked = queue_counts.get(ScheduleStatus.BLOCKED, 0)
    return [
        {"name": "Affiliate links",
         "ok": affiliate_closed,
         "detail": (f"Provider '{settings.affiliate_provider_name}' active — drafts carry tracked "
                    "short links." if affiliate_closed
                    else "No provider configured — links are untracked.")},
        {"name": "Channel admin rights",
         "ok": False,
         "detail": ("The account must be an admin with post rights on the channel. It is currently "
                    "a member, so sends return BLOCKED"
                    + (f" ({blocked} in queue)." if blocked else "."))},
    ]


def top_actions(limit: int = 5) -> list[dict]:
    with session_scope() as s:
        recs = ctx.growth_recommendations(s, limit=limit)
    return recs


def insights() -> dict:
    from src.services.generation.strategy import PostingStrategy

    with session_scope() as s:
        strat = PostingStrategy.load(s)
        emoji_policy = {
            "lead": strat.lead_emojis,
            "avoid": strat.avoid_emojis,
            "rules": [{"emoji": r.emoji, "lift_pct": round(r.lift_pct),
                       "avg_with": round(r.avg_with, 1), "baseline": round(r.baseline, 1),
                       "sample": r.sample} for r in strat.emoji_rules],
            "window": strat.window_desc,
        }
        return {
            "recommendations": ctx.growth_recommendations(s, limit=20),
            "reasoning": ctx.reasoning_insights(s),
            "learnings": ctx.learnings(s),
            "performance": ctx.post_type_performance(s),
            "blueprint": ctx.growth_blueprint(s),
            "style": ctx.channel_style(s),
            "emoji_policy": emoji_policy,
        }


def competitors() -> dict:
    with session_scope() as s:
        return {
            "profiles": ctx.competitor_profiles(s),
            "signals": ctx.competitor_signals(s),
        }


def merchants() -> dict:
    with session_scope() as s:
        return {
            "profiles": ctx.merchant_profiles(s),
            "opportunities": ctx.merchant_opportunities(s),
        }


def plans() -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(CampaignPlan)
                         .where(CampaignPlan.campaign_version == CAMPAIGN_VERSION)
                         .order_by(CampaignPlan.plan_type)).all()
        return [{"plan_type": p.plan_type, "title": p.title,
                 "target_date": p.target_date.isoformat() if p.target_date else None,
                 "confidence": p.confidence, "blueprint": p.blueprint,
                 "expected_outcome": p.expected_outcome, "risks": p.risks} for p in rows]


def _page_meta(total: int, page: int, page_size: int) -> dict:
    pages = max(1, -(-total // page_size)) if page_size else 1
    return {"total": total, "page": page, "page_size": page_size, "pages": pages}


def _clamp_page(page: int, page_size: int) -> tuple[int, int, int]:
    page = max(1, int(page or 1))
    page_size = min(200, max(1, int(page_size or 20)))
    return page, page_size, (page - 1) * page_size


def drafts(page: int = 1, page_size: int = 12) -> dict:
    page, page_size, offset = _clamp_page(page, page_size)
    with session_scope() as s:
        total = s.scalar(select(func.count()).select_from(GeneratedPost)) or 0
        rows = s.scalars(select(GeneratedPost)
                         .order_by(GeneratedPost.generated_at.desc(), GeneratedPost.id.desc())
                         .offset(offset).limit(page_size)).all()
        items = []
        for r in rows:
            meta = r.format_meta or {}
            items.append({
                "id": r.id, "post_type": r.post_type, "status": r.status,
                "bucket": r.selection_bucket, "rank_score": r.rank_score,
                "text": r.rendered_text,
                "affiliate_status": meta.get("affiliate_status"),
                "emoji_policy": meta.get("emoji_policy"),
                "rationale": r.strategy_rationale,
                "generated_at": r.generated_at.isoformat() if r.generated_at else None,
            })
        return {"items": items, **_page_meta(total, page, page_size)}


def posts(page: int = 1, page_size: int = 20) -> dict:
    """Paginated raw post feed (most recent first) with views + preview."""
    page, page_size, offset = _clamp_page(page, page_size)
    with session_scope() as s:
        total = s.scalar(select(func.count()).select_from(Post)) or 0
        rows = s.scalars(select(Post).order_by(Post.posted_at.desc().nullslast(), Post.id.desc())
                         .offset(offset).limit(page_size)).all()
        items = [{"id": p.id, "posted_at": p.posted_at.isoformat() if p.posted_at else None,
                  "views": p.views, "forwards": p.forwards,
                  "preview": ((p.text or "").strip().replace("\n", " ")[:140]),
                  "links": p.links or []} for p in rows]
        return {"items": items, **_page_meta(total, page, page_size)}


def _ist_range_to_utc(start_date, end_date):
    """IST calendar dates (ISO strings/dates) -> [start_utc, end_utc) datetimes."""
    from datetime import datetime, timedelta

    from src.services.analytics.periods import IST

    def _d(v):
        if not v:
            return None
        return v if hasattr(v, "year") else datetime.fromisoformat(v).date()

    sd, ed = _d(start_date), _d(end_date)
    start = datetime(sd.year, sd.month, sd.day, tzinfo=IST) if sd else None
    end = (datetime(ed.year, ed.month, ed.day, tzinfo=IST) + timedelta(days=1)) if ed else None
    return start, end


def analytics(start=None, end=None) -> dict:
    from src.services.analytics import views as vv

    su, eu = _ist_range_to_utc(start, end)
    with session_scope() as s:
        return vv.compute(s, start=su, end=eu)


def data_range() -> dict:
    """Min/max IST post dates so the UI can bound its date pickers."""
    from src.services.analytics.periods import IST, owned_window

    with session_scope() as s:
        w = owned_window(s)
    return {
        "min": w["start"].astimezone(IST).date().isoformat() if w.get("start") else None,
        "max": w["end"].astimezone(IST).date().isoformat() if w.get("end") else None,
    }


def day_summary(day=None) -> dict:
    from src.services.analytics import day as dd

    with session_scope() as s:
        return dd.summarize(s, day)


def queue(page: int = 1, page_size: int = 20) -> dict:
    page, page_size, offset = _clamp_page(page, page_size)
    with session_scope() as s:
        counts = dict(s.execute(
            select(ScheduledPost.status, func.count()).group_by(ScheduledPost.status)).all())
        total = s.scalar(select(func.count()).select_from(ScheduledPost)) or 0
        rows = s.scalars(select(ScheduledPost)
                         .order_by(ScheduledPost.scheduled_at)
                         .offset(offset).limit(page_size)).all()
        items = [{"id": r.id, "post_id": r.generated_post_id, "channel": r.channel_ref,
                  "status": r.status,
                  "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
                  "attempts": f"{r.attempts}/{r.max_attempts}",
                  "note": (r.last_error or "")} for r in rows]
    return {"counts": counts, "items": items, **_page_meta(total, page, page_size)}
