"""Read-only view-model builders for the dashboard.

Everything here is a plain DB read of the engines' STORED outputs — the same
verified data the AI layer is grounded on (reuses ai/context.py). No engine is
re-run and no LLM is called; the dashboard only presents what's already computed.
"""

from __future__ import annotations

from sqlalchemy import func, select

from src.ai import context as ctx
from src.config.settings import get_settings
from src.db.models import Channel, Competitor, CompetitorPost, Post
from src.db.models_automation import ScheduledPost, ScheduleStatus
from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan
from src.db.models_generation import GeneratedPost, PostStatus
from src.db.session import session_scope


def list_channels(org_id: int | None = None) -> list[dict]:
    with session_scope() as s:
        q = select(Channel).order_by(Channel.id)
        if org_id is not None:
            # the org's channels plus any legacy rows not yet assigned to an org
            q = q.where((Channel.org_id == org_id) | (Channel.org_id.is_(None)))
        rows = s.scalars(q).all()
        post_counts = dict(s.execute(
            select(Post.channel_id, func.count()).group_by(Post.channel_id)).all())
        return [{"id": c.id, "username": c.username, "title": c.title, "kind": c.kind,
                 "status": getattr(c, "status", "active"),
                 "resolved": (c.tg_channel_id or 0) > 0,  # negative id = pending resolution
                 "org_id": c.org_id, "posts": post_counts.get(c.id, 0)} for c in rows]


def add_channel(org_id: int | None, username: str, kind: str = "owned") -> dict:
    """Add an owned channel by @username. Telegram's numeric id isn't known until an
    authenticated client resolves it, so the row starts as `pending` with a negative
    placeholder id (real ids are positive). The next Telegram sync adopts it by username
    and flips it to `active`. Competitors are auto-discovered, so this is owned-only."""
    import time

    from src.services.collection.channels import normalize_handle

    handle = normalize_handle(username)
    if not handle:
        return {"ok": False, "error": "Enter a valid @username or t.me link."}
    if kind != "owned":
        return {"ok": False, "error": "Only owned channels are added here; competitors are discovered automatically."}

    with session_scope() as s:
        dup = s.scalar(select(Channel).where(
            func.lower(Channel.username) == handle.lower(),
            (Channel.org_id == org_id) | (Channel.org_id.is_(None))))
        if dup is not None:
            return {"ok": False, "error": f"@{handle} is already added."}
        row = Channel(org_id=org_id, username=handle, kind="owned", status="pending",
                      tg_channel_id=-int(time.time_ns()))  # temp unique negative for the INSERT
        s.add(row)
        s.flush()
        row.tg_channel_id = -row.id   # deterministic, unique, negative → never hits a real id
        s.flush()
        return {"ok": True, "channel": {"id": row.id, "username": row.username,
                "title": None, "kind": "owned", "status": "pending", "resolved": False,
                "org_id": row.org_id, "posts": 0}}


def delete_channel(channel_id: int, confirm: bool = False, org_id: int | None = None) -> dict:
    """Delete a channel and all of its dependent data (posts, metrics, normalized
    rows, classifications, extracted facts). Destructive + irreversible, so a preview
    is returned unless confirm=True. Deletes in FK-dependency order via subqueries
    (no large IN-lists, so it's safe for channels with many posts)."""
    from src.db.models import PostMetricSnapshot
    from src.db.models_classification import PostClassification
    from src.db.models_normalization import (
        ExtractedCoupon, ExtractedLink, ExtractedPrice, NormalizedPost, SourceType)

    with session_scope() as s:
        ch = s.get(Channel, channel_id)
        if ch is None:
            return {"ok": False, "error": f"No channel #{channel_id}."}
        # org guard: don't let one org delete another org's channel
        if org_id is not None and ch.org_id is not None and ch.org_id != org_id:
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
        owned = s.scalars(select(Channel).where(Channel.kind == "owned")
                          .order_by(Channel.participants_count.desc())).first()
        can_view_stats = bool(owned.can_view_stats) if owned else False
        queue_counts = dict(s.execute(
            select(ScheduledPost.status, func.count()).group_by(ScheduledPost.status)).all())
    return {
        "channel": ch,
        "posts": posts,
        "competitors": competitors,
        "drafts": drafts,
        "queue_counts": queue_counts,
        "affiliate_provider": s_.affiliate_provider_name,
        "publishing_gates": _publishing_gates(s_, queue_counts, can_view_stats),
    }


def _publishing_gates(settings, queue_counts: dict, can_view_stats: bool) -> list[dict]:
    """Plain-language status of what still stands between drafts and a live post.

    ``can_view_stats`` reflects the real Channel.can_view_stats flag (set when a
    collection cycle successfully calls the admin-only stats API) rather than a
    fixed assumption, since it also determines whether follower-graph / notification
    stats are ever populated."""
    affiliate_closed = settings.affiliate_provider_name != "generic"
    blocked = queue_counts.get(ScheduleStatus.BLOCKED, 0)
    return [
        {"name": "Affiliate links",
         "ok": affiliate_closed,
         "detail": (f"Provider '{settings.affiliate_provider_name}' active — drafts carry tracked "
                    "short links." if affiliate_closed
                    else "No provider configured — links are untracked.")},
        {"name": "Channel admin rights",
         "ok": can_view_stats,
         "detail": ("Admin stats access confirmed on the last collection cycle." if can_view_stats
                    else "The account must be an admin with post/stats rights on the channel. It is "
                    "currently a member, so sends return BLOCKED"
                    + (f" ({blocked} in queue)." if blocked else "."))},
    ]


def top_actions(limit: int = 5) -> list[dict]:
    with session_scope() as s:
        recs = ctx.growth_recommendations(s, limit=limit)
    return recs


def insights(start: str | None = None, end: str | None = None) -> dict:
    from src.services.generation.strategy import PostingStrategy
    from src.services.intelligence.growth import content_mix_from_rows

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
        blueprint = ctx.growth_blueprint(s)
        date_filtered = bool(start or end)
        if date_filtered:
            su, eu = _ist_range_to_utc(start, end)
            performance = ctx.post_type_performance_range(s, su, eu)
            content_mix = content_mix_from_rows(performance)
        else:
            performance = ctx.post_type_performance(s)
            content_mix = (blueprint.get("blueprint") or {}).get("content_mix")
        return {
            "recommendations": ctx.growth_recommendations(s, limit=20),
            "reasoning": ctx.reasoning_insights(s),
            "performance": performance,
            "content_mix": content_mix,
            "date_filtered": date_filtered,
            "blueprint": blueprint,
            "style": ctx.channel_style(s),
            "emoji_policy": emoji_policy,
        }


def competitors_list() -> list[dict]:
    """Every row in the ``competitors`` table -- for the Settings > Competitors
    management screen (Edit/Delete need every row's id, including freshly-added
    competitors that haven't been profiled yet). Distinct from
    ``ctx.competitor_profiles`` (AI-grounding data, PROFILED competitors only,
    used elsewhere for the dashboard/AI context) -- this is the raw source of
    truth, not a derived view."""
    with session_scope() as s:
        rows = s.scalars(select(Competitor).order_by(Competitor.id)).all()
        post_counts = dict(s.execute(
            select(CompetitorPost.competitor_id, func.count())
            .group_by(CompetitorPost.competitor_id)).all())
        return [{
            "id": c.id,
            "username": c.username,
            "title": c.title,
            "category": c.category,
            "status": c.access_status,
            "last_collected_at": c.last_collected_at.isoformat() if c.last_collected_at else None,
            "posts": post_counts.get(c.id, 0),
            "monitoring_enabled": c.monitoring_enabled,
        } for c in rows]


def competitors() -> dict:
    return {"competitors": competitors_list()}


def competitor_dashboard(window_days: int | None = None) -> dict:
    """Unified competitor dashboard — profiles + benchmarks, grouped by category.

    ``window_days`` when set filters basic stats to the last N days (like comparison).
    """
    from src.services.analytics import comparison as cmp
    from src.services.intelligence.competitor import latest_profiles

    with session_scope() as s:
        # comparison data (owned + competitors with profiles). Show EVERY monitored
        # competitor, not just the top few — compare()'s default cap of 6 was hiding
        # the rest (including manually-added ones that post less). compare() is used
        # only here, so raising the cap affects nothing else.
        n_comp = s.scalar(select(func.count(Competitor.id))) or 0
        comp = cmp.compare(s, window_days=window_days, max_competitors=max(n_comp, 6))
        entities = comp.get("entities", [])

        # raw DB rows for category + benchmark access
        competitors_raw = {
            c.id: c for c in s.scalars(select(Competitor)).all()
        }
        profiles_raw = {p.competitor_id: p for p in latest_profiles(s)}

        # group entities by category
        platform_ents = []
        channel_ents = []
        for e in entities:
            if e.get("is_owned"):
                continue
            # find category from DB
            cid = None
            for _cid, c in competitors_raw.items():
                if c.username == e.get("name"):
                    cid = _cid
                    break
            cat = competitors_raw[cid].category if cid and cid in competitors_raw else None
            e["category"] = cat or "unclassified"
            if cat == "platform":
                platform_ents.append(e)
            else:
                channel_ents.append(e)

        unavailable = comp.get("unavailable", [])
        note = comp.get("note", "")
        metrics = comp.get("metrics", [])

        return {
            "summary": {
                "total": len(entities) - 1,  # exclude owned
                "platform": len(platform_ents),
                "channel": len(channel_ents),
            },
            "platform": platform_ents,
            "channel": channel_ents,
            "unavailable": unavailable,
            "note": note,
            "metrics": metrics,
            "applied_window": window_days,
        }


def competitor_dashboard_trends(days: int = 30) -> dict:
    """Posts/day and views/day for every competitor at once, shared calendar window."""
    from src.services.analytics import competitor_trends as ct

    with session_scope() as s:
        return ct.dashboard_trends(s, days=days)


_COMPETITOR_CATEGORIES = ("platform", "channel")


def create_competitor_record(username: str, category: str) -> dict:
    """Fast half of manually adding a competitor: validate + insert only, so the
    HTTP response doesn't block on the slow pipeline (see run_onboarding_pipeline).
    Idempotent on a duplicate username — returns the existing row instead of
    raising (see onboarding.insert_competitor)."""
    from src.services.collection.onboarding import insert_competitor

    if category not in _COMPETITOR_CATEGORIES:
        raise ValueError(f"category must be one of {_COMPETITOR_CATEGORIES}")
    return insert_competitor(username, category)


def update_competitor(competitor_id: int, category: str | None = None,
                      title: str | None = None,
                      monitoring_enabled: bool | None = None) -> dict:
    """Edit a competitor's ``category``/``title``/``monitoring_enabled`` --
    the only editable fields. ``username`` is immutable (it's the Telegram
    identity collected posts/profiles are keyed to; changing it would orphan
    them), so it isn't accepted here at all. Category is validated the same
    way ``create_competitor_record`` validates it on create.
    ``monitoring_enabled`` gates the daily cron (competitor sync + intel --
    see j_competitor_sync/CompetitorIntelligenceEngine.run): turning it off
    just stops future collection/profiling, it never deletes existing data."""
    if category is not None and category not in _COMPETITOR_CATEGORIES:
        raise ValueError(f"category must be one of {_COMPETITOR_CATEGORIES}")

    with session_scope() as s:
        c = s.get(Competitor, competitor_id)
        if c is None:
            return {"ok": False, "error": f"No competitor #{competitor_id}."}
        if category is not None:
            c.category = category
        if title is not None:
            c.title = title
        if monitoring_enabled is not None:
            c.monitoring_enabled = monitoring_enabled
        s.flush()
        return {"ok": True, "id": c.id, "username": c.username, "title": c.title,
                "category": c.category, "status": c.access_status,
                "last_collected_at": c.last_collected_at.isoformat() if c.last_collected_at else None,
                "monitoring_enabled": c.monitoring_enabled}


def delete_competitor(competitor_id: int, confirm: bool = False) -> dict:
    """Delete a competitor and all of its dependent data (competitor posts,
    normalized rows, classifications, extracted facts, profiles, benchmarks).
    Destructive + irreversible, so a preview is returned unless confirm=True.
    Deletes in FK-dependency order via subqueries (no large IN-lists) --
    mirrors delete_channel's approach exactly, just for the competitor side of
    the schema."""
    from src.db.models_classification import PostClassification
    from src.db.models_competitor_intel import CompetitorBenchmark, CompetitorProfile
    from src.db.models_normalization import (
        ExtractedCoupon, ExtractedLink, ExtractedPrice, NormalizedPost, SourceType)

    with session_scope() as s:
        c = s.get(Competitor, competitor_id)
        if c is None:
            return {"ok": False, "error": f"No competitor #{competitor_id}."}

        post_ids = select(CompetitorPost.id).where(CompetitorPost.competitor_id == competitor_id)
        norm_ids = select(NormalizedPost.id).where(
            NormalizedPost.source_type == SourceType.COMPETITOR,
            NormalizedPost.source_id.in_(post_ids))

        def _count(model, *where):
            return s.scalar(select(func.count()).select_from(model).where(*where)) or 0

        counts = {
            "username": c.username or str(competitor_id),
            "competitor_posts": _count(CompetitorPost, CompetitorPost.competitor_id == competitor_id),
            "normalized_posts": _count(NormalizedPost, NormalizedPost.source_type == SourceType.COMPETITOR,
                                       NormalizedPost.source_id.in_(post_ids)),
            "profiles": _count(CompetitorProfile, CompetitorProfile.competitor_id == competitor_id),
            "benchmarks": _count(CompetitorBenchmark, CompetitorBenchmark.competitor_id == competitor_id),
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
            NormalizedPost.source_type == SourceType.COMPETITOR,
            NormalizedPost.source_id.in_(post_ids)).delete(synchronize_session=False)
        s.query(CompetitorPost).filter(
            CompetitorPost.competitor_id == competitor_id).delete(synchronize_session=False)
        s.query(CompetitorProfile).filter(
            CompetitorProfile.competitor_id == competitor_id).delete(synchronize_session=False)
        s.query(CompetitorBenchmark).filter(
            CompetitorBenchmark.competitor_id == competitor_id).delete(synchronize_session=False)
        s.delete(c)
        return {"ok": True, "deleted": counts}


def run_onboarding_pipeline(username: str) -> None:
    """Slow half: run an already-inserted competitor through the existing
    collection -> link resolution -> normalization -> intelligence pipeline.
    Meant to be scheduled as a FastAPI BackgroundTask after create_competitor_record."""
    from src.services.collection.onboarding import run_pipeline

    run_pipeline(username)


def plans() -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(CampaignPlan)
                         .where(CampaignPlan.campaign_version == CAMPAIGN_VERSION)
                         .order_by(CampaignPlan.plan_type)).all()
        return [{"plan_type": p.plan_type, "title": p.title,
                 "target_date": p.target_date.isoformat() if p.target_date else None,
                 "end_date": p.end_date.isoformat() if p.end_date else None,
                 "confidence": p.confidence, "blueprint": p.blueprint,
                 "expected_outcome": p.expected_outcome, "risks": p.risks,
                 "evidence": p.evidence} for p in rows]


def digest() -> dict:
    from src.db.models_campaign import CampaignPlan, PlanType
    with session_scope() as s:
        p = s.scalars(
            select(CampaignPlan)
            .where(CampaignPlan.plan_type == PlanType.DAILY, CampaignPlan.is_ai_generated == True)  # noqa: E712
            .order_by(CampaignPlan.generated_at.desc())
        ).first()
        if p is None:
            return {"available": False, "digest": "", "plan": None,
                    "factcheck_status": None, "reconciliation": None, "generated_at": None}
        return {
            "available": True,
            "digest": p.ai_digest or "",
            "plan": p.blueprint,
            "factcheck_status": p.factcheck_status,
            "reconciliation": p.reconciliation,
            "generated_at": p.generated_at.isoformat() if p.generated_at else None,
        }


def _page_meta(total: int, page: int, page_size: int) -> dict:
    pages = max(1, -(-total // page_size)) if page_size else 1
    return {"total": total, "page": page, "page_size": page_size, "pages": pages}


def _clamp_page(page: int, page_size: int) -> tuple[int, int, int]:
    page = max(1, int(page or 1))
    page_size = min(200, max(1, int(page_size or 20)))
    return page, page_size, (page - 1) * page_size


def _post_facts(gp) -> dict:
    """Merchant + affiliate status for a generated post, tolerant of both format_meta
    shapes: JIT copywriter posts nest affiliate under `affiliate`; template posts put
    `affiliate_status` at the top level. Returns clean values the UI can trust."""
    meta = gp.format_meta or {}
    aff = meta.get("affiliate") if isinstance(meta.get("affiliate"), dict) else {}
    slot = meta.get("slot") if isinstance(meta.get("slot"), dict) else {}
    merchant = meta.get("primary_merchant") or aff.get("affiliate_merchant") or slot.get("merchant")
    status = meta.get("affiliate_status") or aff.get("affiliate_status")
    return {"merchant": merchant, "affiliate_status": status}


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
            facts = _post_facts(r)
            items.append({
                "id": r.id, "post_type": r.post_type, "status": r.status,
                "bucket": r.selection_bucket, "rank_score": r.rank_score,
                "text": r.rendered_text,
                "merchant": facts["merchant"],
                "affiliate_status": facts["affiliate_status"],
                "emoji_policy": meta.get("emoji_policy"),
                "rationale": r.strategy_rationale,
                "generated_at": r.generated_at.isoformat() if r.generated_at else None,
            })
        return {"items": items, **_page_meta(total, page, page_size)}


def create_draft(*, text: str, post_type: str = "manual",
                 selection_bucket: str | None = None,
                 channel_ref: str | None = None) -> dict:
    from datetime import datetime, timezone
    with session_scope() as s:
        post = GeneratedPost(
            generated_at=datetime.now(timezone.utc),
            post_type=post_type,
            selection_bucket=selection_bucket,
            deal_ids=[],
            rendered_text=text,
            channel_ref=channel_ref,
            status=PostStatus.DRAFT,
        )
        s.add(post)
        s.flush()
        return {"id": post.id, "status": post.status}


def update_draft(draft_id: int, *, text: str | None = None,
                 post_type: str | None = None,
                 status: str | None = None,
                 selection_bucket: str | None = None,
                 channel_ref: str | None = None) -> dict:
    with session_scope() as s:
        post = s.get(GeneratedPost, draft_id)
        if not post:
            return {"ok": False, "error": "Draft not found"}
        if text is not None:
            post.rendered_text = text
        if post_type is not None:
            post.post_type = post_type
        if status is not None:
            post.status = status
        if selection_bucket is not None:
            post.selection_bucket = selection_bucket
        if channel_ref is not None:
            post.channel_ref = channel_ref
        s.flush()
        return {"ok": True, "id": post.id, "post_type": post.post_type,
                "selection_bucket": post.selection_bucket, "status": post.status,
                "channel_ref": post.channel_ref, "text": post.rendered_text}


def delete_draft(draft_id: int) -> dict:
    with session_scope() as s:
        post = s.get(GeneratedPost, draft_id)
        if not post:
            return {"ok": False, "error": "Draft not found"}
        s.delete(post)
        s.flush()
        return {"ok": True, "deleted_id": draft_id}


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
    from datetime import datetime

    from src.services.analytics.periods import ist_day_bounds_utc

    def _d(v):
        if not v:
            return None
        return v if hasattr(v, "year") else datetime.fromisoformat(v).date()

    sd, ed = _d(start_date), _d(end_date)
    start = ist_day_bounds_utc(sd)[0] if sd else None
    end = ist_day_bounds_utc(ed)[1] if ed else None
    return start, end


def analytics(start=None, end=None) -> dict:
    from src.services.analytics import views as vv

    su, eu = _ist_range_to_utc(start, end)
    with session_scope() as s:
        return vv.compute(s, start=su, end=eu)


def data_range() -> dict:
    """Min/max IST post dates so the UI can bound its date pickers."""
    from src.services.analytics.periods import owned_window, to_ist

    with session_scope() as s:
        w = owned_window(s)
    return {
        "min": to_ist(w["start"]).date().isoformat() if w.get("start") else None,
        "max": to_ist(w["end"]).date().isoformat() if w.get("end") else None,
    }


def day_summary(day=None, end=None) -> dict:
    from src.services.analytics import day as dd

    with session_scope() as s:
        return dd.summarize(s, day, end)


def growth(start: str | None = None, end: str | None = None) -> dict:
    from src.services.analytics import growth as gw

    su, eu = _ist_range_to_utc(start, end)
    with session_scope() as s:
        return gw.get_growth(s, su, eu)


def weekly_report(include_ai: bool = True) -> dict:
    """The weekly report: the weekly campaign plan + what changed this period + top
    recommendations, plus (best-effort) an AI weekly briefing in plain language."""
    from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan, PlanType

    with session_scope() as s:
        plan = s.scalar(select(CampaignPlan)
                        .where(CampaignPlan.campaign_version == CAMPAIGN_VERSION,
                               CampaignPlan.plan_type == PlanType.WEEKLY)
                        .order_by(CampaignPlan.generated_at.desc()))
        weekly = None
        ai_summary = None
        if plan:
            weekly = {"title": plan.title, "blueprint": plan.blueprint,
                      "expected_outcome": plan.expected_outcome, "confidence": plan.confidence,
                      "generated_at": plan.generated_at.isoformat() if plan.generated_at else None}
            # The weekly AI plan's digest doubles as the operator's weekly retro — surface
            # the already-generated one rather than making a second AI call.
            if include_ai:
                ai_summary = plan.ai_digest or None
        reasoning = ctx.reasoning_insights(s)
        recs = ctx.growth_recommendations(s, limit=6)

    return {"available": weekly is not None, "weekly_plan": weekly,
            "what_changed": reasoning, "recommendations": recs, "ai_summary": ai_summary}


def retro_latest(week: str | None = None) -> dict:
    """Phase 2.4 -- the WeeklyRetro for ``week`` (an IST Monday, ISO date
    string), or the most recent one when ``week`` is omitted."""
    from datetime import date as date_cls

    from src.db.models_prediction import WeeklyRetro

    with session_scope() as s:
        q = select(WeeklyRetro)
        if week:
            try:
                q = q.where(WeeklyRetro.week_start == date_cls.fromisoformat(week))
            except ValueError:
                return {"available": False, "reason": "week must be YYYY-MM-DD"}
        row = s.scalar(q.order_by(WeeklyRetro.week_start.desc()))
        if row is None:
            return {"available": False, "week_start": None, "metrics": None, "narrative": None}
        return {
            "available": True,
            "week_start": row.week_start.isoformat(),
            "metrics": row.metrics,
            "narrative": row.narrative,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


def _plan_date_bounds(s):
    from src.services.analytics.periods import ist_today, owned_window, to_ist
    w = owned_window(s)
    mn = to_ist(w["start"]).date() if w.get("start") else None
    mx = to_ist(w["end"]).date() if w.get("end") else None
    # The plan is forward-looking ("what to post TODAY"), so the picker must reach today
    # even though the latest OWNED post is usually yesterday — otherwise today isn't
    # selectable and the page can't default to it.
    today = ist_today()
    mx = max(mx, today) if mx else today
    return mn, mx


def _today_details(s, recommended_posts: int):
    """Deterministic 'today' details (posting windows, deal-type allocation, merchant
    mix, risks) sized to ``recommended_posts``, reusing the campaign engine's pure
    helpers so the plan stays consistent with the recommended cadence."""
    from datetime import datetime, timezone
    from src.services.planning.campaign import CampaignPlanningEngine

    bp = (ctx.growth_blueprint(s).get("blueprint") or {})
    eng = CampaignPlanningEngine()
    now = datetime.now(timezone.utc)
    recent = eng._recent_distribution(s, now)
    # The blueprint's posting_plan is sized to the stale baseline, so use it only for
    # the RELATIVE shape and rescale each window to the recommended cadence — otherwise
    # the per-window posts sum to ~18 while the headline says ~50.
    # Fall back to the channel's own historical posting-hours when the Growth
    # blueprint has no posting_plan yet (cold-start / before learning). The
    # fallback is already sized to recommended_posts, so raw_sum ≈ recommended_posts
    # and the rescale below is effectively a no-op for it.
    raw = bp.get("posting_plan") or eng._recent_posting_windows(s, now, recommended_posts)
    raw_sum = sum((p.get("recommended_posts_per_day") or 0) for p in raw) or 1
    windows = [{"part": p.get("part"), "hours": p.get("hours"),
                "posts": round((p.get("recommended_posts_per_day") or 0) * recommended_posts / raw_sum),
                # historical day-part performance, when known — lets the AI cite a real
                # number for WHY this window instead of generic "peak hours" filler.
                "avg_views_per_day": p.get("avg_views_per_day")}
               for p in raw]
    perf = {p["post_type"]: (p["avg_views_per_day"] or 0.0)
            for p in ctx.post_type_performance(s)}
    allocation = eng._allocate_posts(bp, recommended_posts, recent, perf)
    merchants = eng._merchant_allocation(s, recent, now)
    risks = eng._risks(recent, recommended_posts)
    return windows, allocation, merchants, (risks or None)


def _daily_ai_generate(s, day, recommended, windows, allocation, merchants, evt,
                        directive: str | None = None) -> dict:
    """The cache-miss generation path for the daily AI plan: call the planner
    (honoring ``directive`` if given), fact-check its cited numbers against the same
    facts it was grounded on, and persist a `CampaignPlan` row pinned to ``day``.

    Shared by `daily_brief` (normal first-request-of-the-day miss) and
    `regenerate_daily` (forced fresh generation after deleting the stale cache row)
    so the two paths can never drift apart."""
    from src.ai.planner import generate_day_plan
    from src.ai.factcheck import check_cited_numbers
    from src.services.generation.ai_execution import persist_ai_plan

    # Only pass `directive` through when set — keeps the call signature identical
    # to before this feature (and compatible with existing tests that monkeypatch
    # generate_day_plan with a fixed `(s, day=None, inputs=None)` signature) on the
    # normal, non-regenerate path.
    directive_kwargs = {"directive": directive} if directive is not None else {}
    ai_res = generate_day_plan(s, day, inputs={
        "recommended_posts": recommended,
        "posting_windows": windows,
        "deal_type_allocation": allocation,
        "merchant_allocation": merchants,
        "upcoming_event": evt,
    }, **directive_kwargs)
    ai_ok = bool(ai_res.get("available"))
    plan = ai_res.get("plan") or {}
    digest = ai_res.get("digest", "") if ai_ok else ""
    fc_status = None
    row = None
    if ai_ok:
        fc = check_cited_numbers(plan.get("cited_numbers", []), ai_res.get("facts", []))
        fc_status = "pass" if fc["status"] == "passed" else "warn"
        row = persist_ai_plan(s, {**ai_res, "factcheck": fc})
        if row is not None:
            # Pin the cache key to the day we actually planned for — the AI's
            # self-reported "date" inside the plan JSON isn't reliable enough
            # (missing/mismatched) to key the cache lookup on.
            row.target_date = day
            if directive is not None:
                row.operator_directive = directive
    return {"ai_ok": ai_ok, "plan": plan, "digest": digest, "fc_status": fc_status, "row": row}


def ensure_daily_ai_plan(s, day):
    """Generate + persist today's AI daily plan if not already cached, and return the
    row (or None if AI/data unavailable). This is what makes the plan EXIST for the
    just-in-time filler to execute — the plan is the source of truth for scheduling,
    not a dashboard-only artifact. Reuses daily_brief's own input-builders so the
    cron and the dashboard can never produce a differently-shaped plan."""
    from datetime import timedelta
    from src.ai import context as ctx
    from src.services.planning.calendar import upcoming_events
    from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan, PlanType

    cached = s.scalars(
        select(CampaignPlan)
        .where(CampaignPlan.campaign_version == CAMPAIGN_VERSION,
               CampaignPlan.plan_type == PlanType.DAILY,
               CampaignPlan.target_date == day,
               CampaignPlan.is_ai_generated == True)  # noqa: E712
        .order_by(CampaignPlan.generated_at.desc())
    ).first()
    if cached is not None:
        return cached

    _traj = ctx.posting_trajectory(s, days=14, end_day=day - timedelta(days=1))
    # Cold start: if the recent window (14 days ending yesterday) is empty — e.g. a
    # fresh collection whose only posts are TODAY, which that window excludes — fall
    # back to the lifetime average so the plan isn't empty. Truly-zero only when there
    # is no posting history at all.
    recommended = _traj["recent_cadence"] or round(_traj["lifetime_baseline"] or 0)
    windows, allocation, merchants, _ = _today_details(s, recommended)
    evt = None
    try:
        evs = upcoming_events(s, day, within_days=14)
        if evs:
            e = evs[0]
            evt = {"name": e.name, "days_away": (e.next_date - day).days,
                   "date_confidence": e.date_confidence}
    except Exception:
        evt = None
    return _daily_ai_generate(s, day, recommended, windows, allocation, merchants, evt).get("row")


def daily_brief(date: str | None = None, directive: str | None = None) -> dict:
    """The daily plan: what happened YESTERDAY + what to do TODAY, with a cadence
    recommendation grounded in the recent posting trajectory (not the stale lifetime
    baseline). AI writes the narrative + slots best-effort; the numbers are
    deterministic and fact-checked.

    The AI-authored part (digest + slots) is cached per (day, campaign version) as a
    `CampaignPlan` row: the first request for a given day calls the model and persists
    the result; every subsequent request for that SAME day reuses the stored row
    instead of re-calling the AI. A request for a different day always plans fresh.

    ``directive`` is only ever passed by `regenerate_daily` (never by the plain
    `/api/plan/daily` route) — it steers the cache-miss generation, and is only
    reached at all when the caller has already deleted the stale cached row, so a
    normal (non-regenerate) call's behavior is unchanged."""
    from datetime import date as date_cls, timedelta
    from src.services.analytics.day import latest_owned_date
    from src.services.analytics.periods import ist_today
    from src.services.planning.calendar import upcoming_events
    from src.db.models_campaign import PlanType

    with session_scope() as s:
        mn, mx = _plan_date_bounds(s)
        day = None
        if date:
            try:
                day = date_cls.fromisoformat(date)
            except ValueError:
                day = None
        # Default to TODAY (the plan is forward-looking), not the latest owned day —
        # you plan today from yesterday's results before you've posted today. Only the
        # total absence of owned history means there's nothing to plan from.
        if day is None:
            day = ist_today()
        if latest_owned_date(s) is None:
            return {"available": False, "reason": "No owned posts yet."}
        prev = day - timedelta(days=1)

        yesterday = ctx.daily_report_or_live(s, prev)
        traj = ctx.posting_trajectory(s, days=14, end_day=prev)
        recommended = traj["recent_cadence"]
        traj30 = ctx.posting_trajectory(s, days=30, end_day=prev)
        recent_max_30d = max((d["posts"] for d in traj30["days"]), default=0)
        windows, allocation, merchants, risks = _today_details(s, recommended)
        scheduled_count = ctx.scheduled_count_today(s, day)
        gap = max(recommended - scheduled_count, 0)

        evt = None
        try:
            evs = upcoming_events(s, day, within_days=14)
            if evs:
                e = evs[0]
                evt = {"name": e.name, "days_away": (e.next_date - day).days,
                       "date_confidence": e.date_confidence}
        except Exception:
            evt = None

        active = [d["posts"] for d in traj["days"] if d["posts"] > 0]
        lo, hi = (min(active), max(active)) if active else (0, 0)
        det_why = (
            f"Your last {len(active)} active days ran ~{recommended} posts/day "
            f"(range {lo}–{hi}); holding ~{recommended} matches that pace."
            + (f" The old {traj['lifetime_baseline']}/day baseline is a lifetime average "
               "dragged down by early low-activity days — don't plan against it."
               if traj.get("lifetime_baseline") else "")
        )

        cached = s.scalars(
            select(CampaignPlan)
            .where(CampaignPlan.campaign_version == CAMPAIGN_VERSION,
                   CampaignPlan.plan_type == PlanType.DAILY,
                   CampaignPlan.target_date == day,
                   CampaignPlan.is_ai_generated == True)  # noqa: E712
            .order_by(CampaignPlan.generated_at.desc())
        ).first()

        if cached is not None:
            # Same-day repeat request — reuse the persisted AI plan instead of
            # burning another model call. Shape matches a fresh generation below.
            ai_ok = True
            plan = cached.blueprint or {}
            digest = cached.ai_digest or ""
            fc_status = "pass" if cached.factcheck_status == "passed" else "warn"
            plan_row = cached
        else:
            gen = _daily_ai_generate(s, day, recommended, windows, allocation, merchants, evt,
                                      directive=directive)
            ai_ok, plan, digest, fc_status, plan_row = (
                gen["ai_ok"], gen["plan"], gen["digest"], gen["fc_status"], gen["row"])

        if ai_ok and plan.get("recommended_posts") is not None:
            recommended_final, was_clamped = ctx.clamp_recommended_posts(
                plan.get("recommended_posts"), recommended, recent_max_30d)
            ai_why = plan.get("cadence_why")
            cadence_why = ai_why if (not was_clamped and ai_why) else det_why
        else:
            recommended_final, was_clamped = recommended, False
            cadence_why = det_why
        slots = plan.get("post_slots", []) if ai_ok else []
        emphasis = plan.get("emphasis") if ai_ok else None
        watch = plan.get("watch") if ai_ok else None

        return {
            "available": True,
            "date": day.isoformat(), "prev_date": prev.isoformat(),
            "min_date": mn.isoformat() if mn else None,
            "max_date": mx.isoformat() if mx else None,
            "yesterday": yesterday,
            "trajectory": {"days": traj["days"], "recent_cadence": recommended,
                           "lifetime_baseline": traj["lifetime_baseline"]},
            "today": {
                "recommended_posts": recommended_final,
                "cadence_why": cadence_why,
                "posting_windows": windows,
                "deal_type_allocation": allocation,
                "merchant_allocation": merchants,
                "slots": slots,
                "emphasis": emphasis, "watch": watch,
                "risks": risks,
                "confidence": round(min(1.0, len(active) / 14), 3),
                "scheduled_count": scheduled_count,
                "gap": gap,
                "plan_clamped": was_clamped,
            },
            "digest": digest,
            "factcheck_status": fc_status,
            "ai_available": ai_ok,
            "upcoming_event": evt,
            "operator_directive": plan_row.operator_directive if plan_row is not None else None,
            "can_regenerate": day >= ist_today(),
        }


def _weekly_ai_generate(s, week_start, week_end, wk, directive: str | None = None):
    """The cache-miss generation path for the weekly AI narrative: (re)compute the
    deterministic blueprint fresh, call the briefing generator once (honoring
    ``directive`` if given), and persist — updating ``wk`` in place if it already
    exists (blueprint-only row from a CampaignPlanningEngine run) or inserting a
    fresh row otherwise. Returns ``(ai_summary, ai_ok, themes, row)``.

    Shared by `weekly_brief` (normal first-request-of-the-week miss, ``wk`` may be
    an existing blueprint-only row) and `regenerate_weekly` (forced fresh
    generation, always called with ``wk=None`` since the caller already deleted
    the stale row) so the two paths can never drift apart."""
    from src.services.planning.calendar import upcoming_events
    from src.services.planning.campaign import CampaignPlanningEngine
    from src.services.generation.ai_execution import persist_weekly_plan

    bp_growth = (ctx.growth_blueprint(s).get("blueprint") or {})
    perf = {p["post_type"]: (p["avg_views_per_day"] or 0.0)
            for p in ctx.post_type_performance(s)}
    try:
        events = upcoming_events(s, week_start, within_days=30)
    except Exception:
        events = []
    event_data = [{"name": e.name, "next_date": e.next_date,
                   "days_away": (e.next_date - week_start).days,
                   "date_confidence": e.date_confidence} for e in events]
    from datetime import datetime, timezone
    eng = CampaignPlanningEngine()
    recent = eng._recent_distribution(s, datetime.now(timezone.utc))
    blueprint = eng._weekly_plan(
        bp_growth, perf, week_start, event_data, recent)["blueprint"]
    themes = blueprint.get("daily_themes") or []

    ai_summary, ai_ok = "", False
    try:
        from src.ai.client import AIUnavailable
        from src.ai.planner import generate_week_plan
        try:
            res = generate_week_plan(s, week_start, directive=directive)
            ai_summary = res.get("digest") or "" if res.get("available") else ""
            ai_ok = bool(ai_summary)
        except AIUnavailable:
            ai_summary = ""
    except Exception:
        ai_summary = ""

    if wk is not None:
        # Row already exists for this week (e.g. blueprint-only from a legitimate
        # CampaignPlanningEngine run) — update it in place, no new insert, no race risk.
        wk.blueprint = blueprint
        if ai_ok:
            wk.ai_digest = ai_summary
            wk.is_ai_generated = True
        if directive is not None:
            wk.operator_directive = directive
    else:
        wk = persist_weekly_plan(s, week_start, week_end, blueprint,
                                  digest=ai_summary, is_ai_generated=ai_ok)
        if wk is not None and directive is not None:
            wk.operator_directive = directive
    return ai_summary, ai_ok, themes, wk


def weekly_brief(end: str | None = None, directive: str | None = None) -> dict:
    """The weekly view: last 7 days of actual posting + this week's themes + an AI
    weekly narrative (best-effort).

    The week is a real IST calendar week (Monday->Sunday) containing whichever
    date is requested (or today, if none) — NOT a trailing 7-day window ending at
    an arbitrary date. This gives the week a stable identity: viewing any day
    inside the same week always resolves to the same `CampaignPlan` row, so the
    AI-authored digest is generated once per calendar week and reused, the same
    caching contract `daily_brief()` already has. A row's `is_ai_generated`/
    `ai_digest` being unset is literally the "no digest yet, call the AI" tag —
    once set, every later request for that week reuses it, no matter how many
    times the page is reopened.

    ``directive`` is only ever passed by `regenerate_weekly` (never by the plain
    `/api/plan/weekly` route) — same contract as `daily_brief`'s ``directive``."""
    from datetime import date as date_cls, timedelta
    from src.services.analytics.day import latest_owned_date
    from src.services.analytics.daily_report import _owned_channel
    from src.services.analytics.periods import ist_today
    from src.services.planning.calendar import upcoming_events
    from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan, PlanType

    with session_scope() as s:
        anchor = None
        if end:
            try:
                anchor = date_cls.fromisoformat(end)
            except ValueError:
                anchor = None
        if anchor is None:
            anchor = latest_owned_date(s)
        if anchor is None:
            return {"available": False, "reason": "No owned posts yet."}

        # Monday->Sunday IST calendar week containing `anchor`.
        week_start = anchor - timedelta(days=anchor.weekday())
        week_end = week_start + timedelta(days=6)

        traj = ctx.posting_trajectory(s, days=7, end_day=week_end)
        ch = _owned_channel(s)
        deltas = ctx.follower_deltas_by_day(s, ch.id if ch else None, week_start, week_end)
        days = [{"date": d["date"],
                 "weekday": date_cls.fromisoformat(d["date"]).strftime("%a"),
                 "posts": d["posts"], "views_avg": d["views_avg"],
                 **(deltas.get(d["date"]) or {"joined": 0, "left": 0, "net": 0})}
                for d in traj["days"]]
        posts_total = sum(d["posts"] for d in traj["days"])
        views_total = round(sum(d["posts"] * d["views_avg"] for d in traj["days"]))
        totals = {"posts": posts_total, "views_total": views_total,
                  "avg_posts_per_day": round(posts_total / 7, 1)}

        wk = s.scalar(select(CampaignPlan)
                      .where(CampaignPlan.campaign_version == CAMPAIGN_VERSION,
                             CampaignPlan.plan_type == PlanType.WEEKLY,
                             CampaignPlan.target_date == week_start)
                      .order_by(CampaignPlan.generated_at.desc()))

        evs_out = []
        try:
            for e in upcoming_events(s, week_end, within_days=30)[:3]:
                evs_out.append({"name": e.name, "date": e.next_date.isoformat(),
                                "days_away": (e.next_date - week_end).days,
                                "date_confidence": e.date_confidence})
        except Exception:
            pass

        if wk is not None and wk.is_ai_generated and wk.ai_digest:
            # Already generated + persisted for this calendar week — reuse it
            # instead of burning a Groq call on every page view (same idea as the
            # daily cache in daily_brief()).
            ai_summary, ai_ok = wk.ai_digest, True
            themes = (wk.blueprint or {}).get("daily_themes") or []
        else:
            # No cached digest for this exact week (either never generated, or a
            # prior attempt didn't get a usable AI response) — compute the
            # deterministic blueprint fresh (cheap, and doesn't depend on
            # CampaignPlanningEngine's Monday cron ever having run) and try AI once.
            ai_summary, ai_ok, themes, wk = _weekly_ai_generate(
                s, week_start, week_end, wk, directive=directive)

        current_week_start = ist_today() - timedelta(days=ist_today().weekday())
        return {"available": True,
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "days": days, "totals": totals, "themes": themes,
                "recommended_posts_per_day": traj["recent_cadence"],
                "upcoming_events": evs_out, "digest": ai_summary, "ai_available": ai_ok,
                "operator_directive": wk.operator_directive if wk is not None else None,
                "can_regenerate": week_start >= current_week_start}


def regenerate_daily(date: str | None = None, directive: str | None = None) -> dict:
    """Steer & Regenerate — force a fresh AI day plan for ``date`` (or latest owned
    day), optionally steered by a free-text operator ``directive``. Refuses to
    regenerate an already-elapsed IST day (the guidance would land after the fact).
    Deletes the stale cached `CampaignPlan` row first so `daily_brief` takes its
    normal cache-miss path — the SAME generation path a first-ever request for that
    day would take — just with ``directive`` threaded into the planner prompt and
    persisted on the new row."""
    from datetime import date as date_cls
    from sqlalchemy import delete
    from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan, PlanType
    from src.services.ai_outputs import record_ai_output
    from src.services.analytics.day import latest_owned_date
    from src.services.analytics.periods import ist_today

    with session_scope() as s:
        day = None
        if date:
            try:
                day = date_cls.fromisoformat(date)
            except ValueError:
                day = None
        if day is None:
            day = latest_owned_date(s)
        if day is None:
            return {"available": False, "reason": "No owned posts yet."}
        if day < ist_today():
            return {"available": False,
                    "reason": "This day has already elapsed — regenerating it has no effect."}

        # Capture the FULL steering trace before deleting the old plan, so repeated
        # regenerations accumulate (the AI sees every prior ask, not just the latest),
        # and gather today's available merchants so it can explain a request it can't
        # satisfy (e.g. "diversify merchants" when the feed is single-merchant).
        old = s.scalar(select(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.DAILY,
            CampaignPlan.target_date == day).order_by(CampaignPlan.generated_at.desc()))
        # Snapshot the old plan (all cols but id) so we can RESTORE it if regeneration
        # fails — otherwise a failed regen (e.g. AI at quota) destroys the good plan.
        old_snap = ({c.name: getattr(old, c.name) for c in CampaignPlan.__table__.columns
                     if c.name != "id"} if old is not None else None)
        trace = list((old.blueprint or {}).get("steering_history") or []) if old else []
        if directive:
            trace.append(directive)
        avail = sorted({d.get("merchant_key") for d in ctx.available_deals(s, limit=30)
                        if d.get("merchant_key")})
        s.execute(delete(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.DAILY,
            CampaignPlan.target_date == day,
        ))

    # Compose a directive that carries the whole steering history + what's actually
    # available, so the AI addresses the repeated ask instead of silently repeating.
    composed = directive
    if len(trace) > 1:  # only when there ARE prior asks — the "you've been asked N times" framing
        composed = (
            f"You have been asked to adjust THIS day's plan {len(trace)} time(s). Address the "
            "LATEST request and acknowledge the earlier ones — do NOT silently reproduce the "
            "same plan.\nSTEERING HISTORY (oldest first):\n"
            + "\n".join(f"  {i + 1}. {d}" for i, d in enumerate(trace))
            + f"\n\nMerchants with deals in today's feed: {avail or 'none'}."
        )
    result = daily_brief(date=day.isoformat(), directive=composed)
    # Success is measured by an actual AI plan being PERSISTED — not result["available"]
    # (daily_brief still returns available=True with the deterministic fallback when the
    # AI is down). If no AI row landed, the regeneration failed: restore the old plan.
    with session_scope() as s2:
        row = s2.scalar(select(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.DAILY,
            CampaignPlan.target_date == day,
            CampaignPlan.is_ai_generated == True).order_by(CampaignPlan.generated_at.desc()))  # noqa: E712
        if row is not None:
            # success — persist the RAW trace so the next regeneration accumulates it;
            # keep operator_directive as just the latest raw ask (not the composed blob).
            row.blueprint = {**(row.blueprint or {}), "steering_history": trace}
            row.operator_directive = directive
        elif old_snap is not None:
            # regeneration produced no AI plan (AI unavailable) — restore the previous one
            # so the day is never left plan-less with an orphaned queue.
            s2.add(CampaignPlan(**old_snap))
    if row is None and old_snap is not None:
        return {"available": False, "restored": True,
                "reason": f"Regeneration failed ({result.get('reason') or 'AI unavailable'}) "
                          "— kept your existing plan."}
    if row is not None:
        note = f"daily {day.isoformat()} — directive: {directive[:200] if directive else '(none)'}"
        record_ai_output("plan_regenerated", note, get_settings().ai_model)
    return result


def regenerate_weekly(end: str | None = None, directive: str | None = None) -> dict:
    """Steer & Regenerate — force a fresh AI weekly narrative for the calendar week
    containing ``end`` (or latest owned day), optionally steered by a free-text
    operator ``directive``. Refuses to regenerate a week that has already fully
    elapsed (its Monday is before the current IST week's Monday) — the guidance
    would land after the fact. Deletes the stale cached `CampaignPlan` row first so
    `weekly_brief` takes its normal cache-miss path, with ``directive`` threaded
    into the briefing prompt and persisted on the new row."""
    from datetime import date as date_cls, timedelta
    from sqlalchemy import delete
    from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan, PlanType
    from src.services.ai_outputs import record_ai_output
    from src.services.analytics.day import latest_owned_date
    from src.services.analytics.periods import ist_today

    with session_scope() as s:
        anchor = None
        if end:
            try:
                anchor = date_cls.fromisoformat(end)
            except ValueError:
                anchor = None
        if anchor is None:
            anchor = latest_owned_date(s)
        if anchor is None:
            return {"available": False, "reason": "No owned posts yet."}

        week_start = anchor - timedelta(days=anchor.weekday())
        today = ist_today()
        current_week_start = today - timedelta(days=today.weekday())
        if week_start < current_week_start:
            return {"available": False,
                    "reason": "This day has already elapsed — regenerating it has no effect."}

        s.execute(delete(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.WEEKLY,
            CampaignPlan.target_date == week_start,
        ))

    result = weekly_brief(end=week_start.isoformat(), directive=directive)
    if result.get("available"):
        note = f"weekly {week_start.isoformat()} — directive: {directive[:200] if directive else '(none)'}"
        record_ai_output("plan_regenerated", note, get_settings().ai_model)
    return result


def queue(page: int = 1, page_size: int = 20) -> dict:
    page, page_size, offset = _clamp_page(page, page_size)
    with session_scope() as s:
        counts = dict(s.execute(
            select(ScheduledPost.status, func.count()).group_by(ScheduledPost.status)).all())
        total = s.scalar(select(func.count()).select_from(ScheduledPost)) or 0
        rows = s.scalars(select(ScheduledPost)
                         .order_by(ScheduledPost.scheduled_at)
                         .offset(offset).limit(page_size)).all()
        # attach each queued draft's real content so the schedule is legible: the post
        # text (what actually goes out), its type and merchant — not just the internal
        # selection_bucket key the old UI showed.
        gps = {}
        pids = [r.generated_post_id for r in rows if r.generated_post_id]
        if pids:
            for gp in s.scalars(select(GeneratedPost).where(GeneratedPost.id.in_(pids))):
                gps[gp.id] = gp
        items = []
        for r in rows:
            gp = gps.get(r.generated_post_id)
            facts = _post_facts(gp) if gp is not None else {"merchant": None, "affiliate_status": None}
            items.append({
                "id": r.id, "post_id": r.generated_post_id, "channel": r.channel_ref,
                "post_type": gp.post_type if gp is not None else None,
                "merchant": facts["merchant"], "affiliate_status": facts["affiliate_status"],
                "text": gp.rendered_text if gp is not None else None,
                "bucket": gp.selection_bucket if gp is not None else None,
                "status": r.status,
                "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
                "attempts": f"{r.attempts}/{r.max_attempts}",
                "note": (r.last_error or "")})
    return {"counts": counts, "items": items, **_page_meta(total, page, page_size)}


def _cadence_minutes_by_key() -> dict[str, int]:
    """Every job's cadence expressed in minutes, derived from cadences.py constants
    (interval jobs use their _MIN/_HOURS constant directly; daily/weekly/monthly jobs
    use the calendar-fact multipliers 24*60 / 7*24*60 / 30*24*60)."""
    from src.controllers import cadences as C

    day, week, month = 24 * 60, 7 * 24 * 60, 30 * 24 * 60
    return {
        "telegram_sync": C.TELEGRAM_SYNC_MIN,
        "competitor_sync": C.COMPETITOR_SYNC_MIN,
        "normalize_posts": C.NORMALIZE_POSTS_MIN,
        "stats_refresh": C.STATS_REFRESH_MIN,
        "link_resolution": C.LINK_RESOLUTION_DEFAULT_MIN,
        "growth_detection": day,
        "competitor_discover": day,
        "competitor_intel": day,
        "weekly_retro": week,
        "weekly_report": week,
        "monthly_report": month,
        "learning": day,
        "queue_processor": C.QUEUE_PROCESSOR_MIN,
        "url_health": C.URL_HEALTH_HOURS * 60,
        "merchant_feed_sync": C.MERCHANT_FEED_SYNC_MIN,
        "notification_engine": C.NOTIFICATION_ENGINE_MIN,
        "org_health": C.ORG_HEALTH_HOURS * 60,
        "db_cleanup": day,
        "daily_report": day,
        "daily_plan": day,
    }


def _aware_utc(dt):
    """SQLite can hand back naive datetimes for tz-aware columns; treat naive as UTC
    (that's the only tz this app ever writes) so age math never raises."""
    from datetime import timezone
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def scheduler_runs(limit: int = 100, job: str | None = None) -> dict:
    """Recent SchedulerRun rows plus a per-job status summary, for the Schedulers page."""
    from datetime import datetime, timezone
    from src.controllers.schedulers import JOBS
    from src.db.models_scheduler import SchedulerRun

    cadence_minutes = _cadence_minutes_by_key()
    with session_scope() as s:
        q = select(SchedulerRun).order_by(SchedulerRun.id.desc())
        if job:
            q = q.where(SchedulerRun.scheduler_key == job)
        rows = s.scalars(q.limit(limit)).all()
        runs = [{"key": r.scheduler_key, "status": r.status, "detail": r.detail,
                 "error": r.error, "processed": r.records_processed,
                 "duration_ms": r.duration_ms,
                 "at": r.started_at.isoformat() if r.started_at else None} for r in rows]

        now = datetime.now(timezone.utc)
        jobs = []
        for j in JOBS:
            last = s.scalar(select(SchedulerRun).where(SchedulerRun.scheduler_key == j.key)
                            .order_by(SchedulerRun.id.desc()))
            cmin = cadence_minutes.get(j.key, 24 * 60)
            last_started_at = _aware_utc(last.started_at) if last else None
            overdue = None
            if last_started_at is not None:
                age_min = (now - last_started_at).total_seconds() / 60
                overdue = age_min > 2 * cmin
            jobs.append({
                "key": j.key, "name": j.name, "cadence": j.cadence, "priority": j.priority,
                "last_status": last.status if last else None,
                "last_detail": last.detail if last else None,
                "last_error": last.error if last else None,
                "last_started_at": last_started_at.isoformat() if last_started_at else None,
                "last_duration_ms": last.duration_ms if last else None,
                "cadence_minutes": cmin,
                "overdue": overdue,
            })
    return {"jobs": jobs, "runs": runs}
