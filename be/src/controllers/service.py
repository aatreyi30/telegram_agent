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
    from src.services.analytics import deal_gap
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
            "deal_gap": deal_gap.compute(s, window_days=window_days or 30),
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


def _today_details(s, recommended_posts: int, day=None):
    """Deterministic 'today' details (posting windows, deal-type allocation, merchant
    mix, risks) sized to ``recommended_posts``, reusing the campaign engine's pure
    helpers so the plan stays consistent with the recommended cadence.

    ``day`` (the plan date) windows the DISPLAYED 'avg views/post' + sample to the 30
    days ending the day before ``day`` — so it moves as you change dates instead of
    always showing the all-time snapshot. The split/target above stays on the stable
    all-time learning snapshot (only the shown per-post figure is windowed). Falls back
    to the all-time snapshot when ``day`` is None."""
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
    shares = [(p.get("recommended_posts_per_day") or 0) for p in raw]
    raw_sum = sum(shares)
    n_win = len(raw)
    if n_win == 0:
        windows = []
    else:
        # Floor each window then hand the remainder to the largest-share windows so the
        # per-window posts sum to recommended_posts EXACTLY. Old code round()'d each
        # window independently (they didn't sum to the headline) and used `raw_sum ... or 1`
        # so an all-zero posting_plan made EVERY window show 0 while the headline said N.
        if raw_sum > 0:
            counts = [int(sh * recommended_posts / raw_sum) for sh in shares]
        else:
            counts = [recommended_posts // n_win] * n_win   # no signal -> spread evenly
        remainder = recommended_posts - sum(counts)
        order = sorted(range(n_win), key=lambda i: (-shares[i], i))
        j = 0
        while remainder > 0:
            counts[order[j % n_win]] += 1
            remainder -= 1
            j += 1
        windows = [{"part": p.get("part"), "hours": p.get("hours"),
                    "posts": counts[i],
                    # historical day-part performance, when known — lets the AI cite a real
                    # number for WHY this window instead of generic "peak hours" filler.
                    "avg_views_per_day": p.get("avg_views_per_day")}
                   for i, p in enumerate(raw)]
    _ptp = ctx.post_type_performance(s)
    perf = {p["post_type"]: (p["avg_views_per_day"] or 0.0) for p in _ptp}
    # Genuine, intuitive per-post figure (real average of real view counts, ~780/577
    # here) as opposed to the age-confounded views/day velocity (~10/31), which
    # divides lifetime views by post age and so understates older post types. This is
    # what the Plan page displays; see AVG-VIEWS note. Windowed to the selected date
    # (30 days ending yesterday) when ``day`` is given, so the number moves per date
    # instead of always showing the all-time snapshot; the split/target above stays on
    # the stable all-time snapshot. A type with no posts that window falls to "—".
    _disp = _ptp
    if day is not None:
        from datetime import timedelta
        from src.services.analytics.periods import ist_day_bounds_utc
        prev = day - timedelta(days=1)
        w_start, _ = ist_day_bounds_utc(prev - timedelta(days=29))
        _, w_end = ist_day_bounds_utc(prev)
        _disp = ctx.post_type_performance_range(s, w_start, w_end) or _ptp
    views_per_post = {p["post_type"]: p.get("avg_views") for p in _disp}
    # Sample size behind each avg — surfaced beside the number so the Plan page can
    # show "measured across N posts", making the figure self-evidently real (not an
    # estimate). Deterministic provenance, not a new signal.
    views_sample = {p["post_type"]: p.get("posts") for p in _disp}
    allocation = eng._allocate_posts(bp, recommended_posts, recent, perf)
    # Unify the displayed numbers to the canonical PostTypePerformance values (the
    # learning engine's output the rest of the app uses) so the Plan page can't show
    # a divergent GrowthEngine figure. Split (target_posts) is left exactly as
    # _allocate_posts computed it — only the displayed metrics are set here.
    for a in allocation:
        canon = perf.get(a.get("post_type"))
        if canon is not None:
            a["avg_views_per_day"] = canon
        vpp = views_per_post.get(a.get("post_type"))
        if vpp is not None:
            a["avg_views_per_post"] = vpp
        n = views_sample.get(a.get("post_type"))
        if n is not None:
            a["views_sample"] = n
    # Deterministic per-type reasoning for the Plan page's "Why" column — explains the
    # split and the views figure straight from the real numbers that produced them, so
    # it's guaranteed to match the computed allocation. (Not an LLM rationalization,
    # which could contradict the deterministic split — the whole point is trust.)
    # Count-free on purpose: daily_brief rebuckets target_posts from the ACTUAL slots
    # afterwards, so hardcoding a count here could drift from the number shown. The count
    # is its own column; this explains the VIEWS figure and WHY the split leans as it does.
    _vpp = {a.get("post_type"): a.get("avg_views_per_post") for a in allocation}
    _sv, _lv = _vpp.get("single_deal"), _vpp.get("loot_deal")
    for a in allocation:
        pt = a.get("post_type")
        vpp = a.get("avg_views_per_post")
        mine = _sv if pt == "single_deal" else _lv
        other = _lv if pt == "single_deal" else _sv
        other_label = "loot boards" if pt == "single_deal" else "single deals"
        bits: list[str] = []
        if vpp is not None:
            samp = f" across {a['views_sample']:,} posts" if a.get("views_sample") else ""
            bits.append(f"averages {round(vpp)} views/post over the last 30 days{samp}")
        if mine is not None and other is not None:
            if mine >= other:
                bits.append(f"ahead of {other_label} ({round(other)}/post), so the mix leans this type")
            else:
                bits.append(f"just behind {other_label} ({round(other)}/post), but kept in the mix so "
                            "both types keep running (30% variety floor)")
        a["reasoning"] = ("This type " + "; ".join(bits) + "." if bits
                          else "Set by the channel's learned single/loot mix.")
    merchants = eng._merchant_allocation(s, recent, now)
    risks = eng._risks(recent, recommended_posts)
    return windows, allocation, merchants, (risks or None)


def _llm_allocation_reasoning(allocation: list[dict]) -> dict:
    """One small, grounded LLM call: a plain-English one-liner per deal type for the Plan
    page's 'Why' column. Deliberately COUNT-FREE: it's fed the views figures + which type
    leads, NEVER the post count — because the count is rebucketed to the real slots AFTER
    this runs, so a cited count would go stale (single 'gets 27 posts' while the table
    shows 21). It explains the views + the lean; the count lives in its own column. Any
    sentence citing a number NOT in the inputs (e.g. a hallucinated count) is dropped.
    Returns {post_type: sentence}; '{}' on failure (deterministic fallback stays)."""
    import json as _json

    from src.ai.client import AIClient, AIUnavailable
    from src.ai.factcheck import check_cited_numbers, extract_prose_numbers
    from src.ai.planner import _extract_json_object, _loads_lenient

    # Rank by views so the prompt can name which type leads WITHOUT a post count.
    _ranked = sorted([a for a in allocation if a.get("avg_views_per_post") is not None],
                     key=lambda a: -a["avg_views_per_post"])
    _lead = _ranked[0].get("post_type") if _ranked else None
    rows = [{"deal_type": a.get("deal_type"), "post_type": a.get("post_type"),
             "avg_views_per_post": (round(a["avg_views_per_post"])
                                    if a.get("avg_views_per_post") is not None else None),
             "measured_across_posts": a.get("views_sample"),
             "leads_on_views": a.get("post_type") == _lead}
            for a in allocation if a.get("post_type")]
    if not rows:
        return {}
    system = (
        "You explain a deals channel's deal-type mix to its operator for a 'Why' column. For "
        "EACH deal type in DATA, write ONE short, plain, conversational sentence: what its "
        "average views/post is and why it gets more or less emphasis (the type that leads on "
        "views is favoured; both still run for variety). Use ONLY numbers present in DATA. "
        "CRITICAL: do NOT state any post count or percentage — those live in another column "
        "and would go stale here. No fluff, no unmeasurable claims (no conversion/CTR/revenue). "
        "Output EXACTLY one JSON object mapping each post_type to its sentence, e.g. "
        '{"single_deal":"...","loot_deal":"..."} — no text outside the JSON.')
    try:
        raw = AIClient().complete("DATA:\n" + _json.dumps(rows), system_extra=system,
                                  max_tokens=400, trace_call="alloc_reason")
    except AIUnavailable:
        return {}
    obj = _extract_json_object(raw)
    if obj is None:
        return {}
    try:
        parsed = _loads_lenient(obj)
    except Exception:
        return {}
    # Only the VIEWS numbers are allowed in the prose (no counts fed in) — a sentence citing
    # anything else (a hallucinated post count/percentage) is dropped, deterministic kept.
    _nums = [v for r in rows for v in (r["avg_views_per_post"], r["measured_across_posts"])
             if v is not None]
    allowed = [{f"n{i}": v for i, v in enumerate(_nums)}]
    out: dict = {}
    for pt, sentence in (parsed or {}).items():
        if not isinstance(sentence, str) or not sentence.strip():
            continue
        # `digest` is one of the keys extract_prose_numbers actually scans — pull the
        # sentence's numbers through it and verify each against the allowed inputs.
        fc = check_cited_numbers(extract_prose_numbers({"digest": sentence}), allowed)
        if fc.get("status") != "failed":   # pass/warn ok; a hard fail means an invented number
            out[pt] = sentence.strip()
    return out


def _daily_ai_generate(s, day, recommended, windows, allocation, merchants, evt,
                        directive: str | None = None, recent_max_30d: int | None = None) -> dict:
    """The cache-miss generation path for the daily AI plan: call the planner
    (honoring ``directive`` if given), fact-check its cited numbers against the same
    facts it was grounded on, and persist a `CampaignPlan` row pinned to ``day``.
    ``recent_max_30d`` (when the caller has it) feeds the G10 persist-time clamp —
    ``recommended`` doubles as the clamp's recent-median bound.

    Shared by `daily_brief` (normal first-request-of-the-day miss) and
    `regenerate_daily` (forced fresh generation after deleting the stale cache row)
    so the two paths can never drift apart."""
    from src.ai.planner import generate_day_plan
    from src.ai.factcheck import (check_cited_numbers, extract_prose_numbers,
                                   plan_structural_numbers, unmeasurable_claims)
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
        # G6: a deterministic fallback plan carries no cited_numbers to fact-check —
        # tag it "fallback" directly (persist_ai_plan/daily_brief both special-case
        # this status) instead of running it through check_cited_numbers.
        if plan.get("is_fallback"):
            fc = {"status": "fallback"}
            fc_status = "fallback"
        else:
            # Fact-check the PROSE, not the model's always-empty `cited_numbers`
            # (see ai/factcheck.py). The plan's own decision numbers go into the
            # pool as one flat dict so restating them never flags as fabrication.
            structural = plan_structural_numbers(plan)
            facts_pool = [*ai_res.get("facts", []), {f"s{i}": v for i, v in enumerate(structural)}]
            fc = check_cited_numbers(extract_prose_numbers({**plan, "digest": digest}), facts_pool)
            fc_status = ("pass" if fc["status"] == "passed"
                        else "failed" if fc["status"] == "failed" else "warn")
            # Qualitative guard the number-check can't do: prose asserting an outcome
            # we don't track (conversion/CTR/revenue — no click/affiliate data exists)
            # is ungrounded. Downgrade a clean plan to 'warn' and record the terms so
            # it's visible rather than silently trusted.
            bad_claims = unmeasurable_claims({**plan, "digest": digest})
            if bad_claims:
                # Record the offending terms and never let such a plan read as fully
                # trusted — downgrade a clean 'pass' to 'warn' (a real 'failed' stays).
                fc = {**fc, "unmeasurable": bad_claims}
                if fc_status == "pass":
                    fc_status = "warn"
        # LLM-authored reasoning for the deal-type table's Why column — a small grounded,
        # fact-checked call, attached to the plan so it's cached in the blueprint (generated
        # once per plan, not per page-load). Skipped for a fallback plan (no AI to trust).
        if ai_ok and not plan.get("is_fallback"):
            _ar = _llm_allocation_reasoning(allocation)
            if _ar:
                plan["allocation_reasoning"] = _ar
        # Current IST minute-of-day when planning TODAY — lets persist floor a hard time
        # window at "now" so a partial-future steer ("after 6pm" sent at 8pm) places all
        # its slots in the remaining window instead of thinning into already-past minutes.
        from datetime import datetime as _dt, timezone as _tz
        from src.services.analytics.periods import ist_today, to_ist
        _now_min = None
        if day == ist_today():
            _n = to_ist(_dt.now(_tz.utc))
            _now_min = _n.hour * 60 + _n.minute
        row = persist_ai_plan(s, {**ai_res, "factcheck": fc},
                              recent_median=recommended, recent_max_30d=recent_max_30d,
                              steered=bool(directive), now_min=_now_min)
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
    windows, allocation, merchants, _ = _today_details(s, recommended, day=day)
    # Same clamp ceiling `daily_brief` uses (G10) — computed here too so the cron
    # path clamps at persist time exactly like the dashboard path does.
    traj30 = ctx.posting_trajectory(s, days=30, end_day=day - timedelta(days=1))
    recent_max_30d = max((d["posts"] for d in traj30["days"]), default=0)
    evt = None
    try:
        evs = upcoming_events(s, day, within_days=14)
        if evs:
            e = evs[0]
            evt = {"name": e.name, "days_away": (e.next_date - day).days,
                   "date_confidence": e.date_confidence}
    except Exception:
        evt = None
    return _daily_ai_generate(s, day, recommended, windows, allocation, merchants, evt,
                              recent_max_30d=recent_max_30d).get("row")


def daily_brief(date: str | None = None, directive: str | None = None,
                target_posts: int | None = None) -> dict:
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
        # Explicit quantity steer ("post 20 today") overrides the learned cadence as the
        # target count. Still safety-clamped at persist (G10) against 3x the recent max,
        # so an extreme ask is capped + flagged rather than trusted blindly.
        if target_posts:
            recommended = target_posts
        traj30 = ctx.posting_trajectory(s, days=30, end_day=prev)
        recent_max_30d = max((d["posts"] for d in traj30["days"]), default=0)
        windows, allocation, merchants, risks = _today_details(s, recommended, day=day)
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

        def _det_why(n: int) -> str:
            """The cadence explanation, keyed to the ACTUAL displayed count ``n`` so the
            headline number and this sentence can never name different figures. Only
            claims "matches that pace" when ``n`` sits inside the observed active-day
            range; otherwise it states the plan plainly (the historical ~median is still
            shown as the descriptive baseline, which is a true, separate fact)."""
            ran = (f"Your last {len(active)} active days ran ~{recommended} posts/day "
                   f"(range {lo}–{hi})")
            pace = (f"; holding ~{n} matches that pace." if lo <= n <= hi
                    else f"; planning ~{n} today.")
            tail = (f" The old {traj['lifetime_baseline']}/day baseline is a lifetime average "
                    "dragged down by early low-activity days — don't plan against it."
                    if traj.get("lifetime_baseline") else "")
            return ran + pace + tail

        from sqlalchemy import or_
        cached = s.scalars(
            select(CampaignPlan)
            .where(CampaignPlan.campaign_version == CAMPAIGN_VERSION,
                   CampaignPlan.plan_type == PlanType.DAILY,
                   CampaignPlan.target_date == day,
                   CampaignPlan.is_ai_generated == True,  # noqa: E712
                   # Never cache-serve a deterministic FALLBACK row: it was written
                   # because the AI was down at the time, so serving it freezes the
                   # whole day on the outage. Skipping it means the next page load
                   # re-attempts the AI and auto-heals once it (or the groq failover)
                   # is back. ponytail: re-attempts per refresh during an outage — a
                   # model call each; fine, it's the "keep trying" behavior we want.
                   or_(CampaignPlan.factcheck_status.is_(None),
                       CampaignPlan.factcheck_status != "fallback"))
            .order_by(CampaignPlan.generated_at.desc())
        ).first()

        if cached is not None:
            # Same-day repeat request — reuse the persisted AI plan instead of
            # burning another model call. Shape matches a fresh generation below.
            ai_ok = True
            plan = cached.blueprint or {}
            digest = cached.ai_digest or ""
            fc_status = ("fallback" if cached.factcheck_status == "fallback"
                        else "skipped" if cached.factcheck_status == "skipped"
                        else "pass" if cached.factcheck_status == "passed"
                        else "failed" if cached.factcheck_status == "failed"
                        else "warn")
            plan_row = cached
        else:
            gen = _daily_ai_generate(s, day, recommended, windows, allocation, merchants, evt,
                                      directive=directive, recent_max_30d=recent_max_30d)
            ai_ok, plan, digest, fc_status, plan_row = (
                gen["ai_ok"], gen["plan"], gen["digest"], gen["fc_status"], gen["row"])

        if fc_status == "failed":
            # FIX 2 — a failed fact-check means the digest itself likely cites a
            # fabricated number; never surface it to the operator as if trusted.
            # The plan row still persists with its real `failed` status (so
            # jit_fill's existing (passed/warn) check already refuses to fill it).
            digest = ("This plan could not be verified against the data (some cited "
                      "numbers are unsupported) — regenerate it.")

        if ai_ok and plan.get("recommended_posts") is not None:
            # recommended_posts is already clamped at persist time (G10); read the
            # recorded flag rather than re-clamping (which would see the clamped value
            # as in-range and report was_clamped=False). Also survives the cache-hit path.
            recommended_final = plan.get("recommended_posts")
            was_clamped = bool(plan.get("plan_clamped"))
            # Always the deterministic, data-driven cadence line, keyed to the DISPLAYED
            # count so headline and explanation can't disagree. The AI's own cadence_why
            # drifts (it once said "19 posts/day" when the number was 38); _det_why is
            # computed from the real trajectory, so it stays accurate AND adapts.
            cadence_why = _det_why(recommended_final)
        else:
            recommended_final, was_clamped = recommended, False
            cadence_why = _det_why(recommended_final)
        slots = plan.get("post_slots", []) if ai_ok else []
        emphasis = plan.get("emphasis") if ai_ok else None
        watch = plan.get("watch") if ai_ok else None

        # The displayed deal-type allocation must reflect the plan ACTUALLY produced.
        # The AI can deviate from the deterministic split (e.g. lean loot per the
        # week direction), which showed the table as 30/8 while the schedule posted
        # 23/15. Recompute target_posts from the real slots (the avg_views_per_post
        # figure stays as the canonical metric). `allocation` was already handed to
        # the generator above, so this only corrects the DISPLAY, not the AI input.
        if slots and allocation:
            # Bucket by loot-vs-single MEANING, not a literal type string — the model
            # drifts across single|collection|loot_deal|single_deal (see constants.py),
            # so a string map alone splits loot across keys and mis-tallies the table.
            from src.services.generation.constants import is_loot_type
            _actual: dict = {}
            for _sl in slots:
                _k = "loot_deal" if is_loot_type(_sl.get("type")) else "single_deal"
                _actual[_k] = _actual.get(_k, 0) + 1
            for _a in allocation:
                _a["target_posts"] = _actual.get(_a.get("post_type"), 0)
            allocation = [_a for _a in allocation if (_a.get("target_posts") or 0) > 0]

        # Overlay the LLM-authored per-type reasoning (grounded + fact-checked at
        # generation, cached in the blueprint) onto the Why column. Each row already
        # carries a deterministic reasoning; the LLM one only REPLACES it when present, so
        # a fresh channel / AI-down / cron plan still shows the deterministic explanation.
        _alloc_reason = plan.get("allocation_reasoning") if isinstance(plan, dict) else None
        if _alloc_reason:
            for _a in allocation:
                _r = _alloc_reason.get(_a.get("post_type"))
                if _r:
                    _a["reasoning"] = _r

        # Same alignment for posting windows: they're built from the deterministic
        # recent cadence, so when the AI plans fewer posts (e.g. 15) the windows still
        # summed to the raw cadence (38 as 1/5/18/14). Rebucket the ACTUAL slots into
        # the day-parts so the window counts always sum to the real plan.
        if slots and windows:
            def _part_of(hr: int) -> str:
                return ("Late night" if hr < 6 else "Morning" if hr < 12
                        else "Afternoon" if hr < 18 else "Evening")
            _wc: dict = {}
            for _sl in slots:
                _h = (_sl.get("time_ist") or "").split(":")[0]
                if not _h.isdigit():
                    continue
                _p = _part_of(int(_h) % 24)
                _wc[_p] = _wc.get(_p, 0) + 1
            for _w in windows:
                _w["posts"] = _wc.get(_w.get("part"), 0)
            windows = [_w for _w in windows if (_w.get("posts") or 0) > 0]

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
            # True when a pre-steer snapshot exists to undo to — the FE shows a "Revert" action.
            "can_revert": (day >= ist_today()
                           and bool((plan_row.blueprint or {}).get("_pre_steer"))
                           if plan_row is not None else False),
        }


def _grounded_weekly_summary(s, end_day=None) -> str:
    """Honest, deterministic weekly retro from REAL data only — used when the AI
    narrative fails fact-check (it cited self-computed/unverifiable figures). No LLM,
    no derived numbers: the week's actual posts/views, its strongest day, and the
    measured per-post views per deal type, so the operator gets a genuinely useful
    grounded read instead of an apology. Ends with a stable 'Grounded summary' marker
    the Plan page keys on to suppress the redundant 'failed — regenerate' warning."""
    traj = ctx.posting_trajectory(s, days=7, end_day=end_day)
    days = traj.get("days") or []
    total_posts = sum(d["posts"] for d in days)
    total_views = sum((d.get("views") or 0) for d in days)
    active = [d for d in days if d["posts"]]
    ptp = {p["post_type"]: p for p in ctx.post_type_performance(s)}
    sv = (ptp.get("single_deal") or {}).get("avg_views")
    lv = (ptp.get("loot_deal") or {}).get("avg_views")

    parts: list[str] = []
    if total_posts:
        line = f"Last 7 days: {total_posts} posts drawing {total_views:,} views"
        if active:
            best = max(active, key=lambda d: d.get("views_avg") or 0)
            line += (f", strongest on {best['date']} at {round(best.get('views_avg') or 0)} "
                     "avg views/post")
        parts.append(line)
    if sv and lv:
        if sv >= lv:
            parts.append(f"per post, single deals ({round(sv)} views) out-perform loot boards "
                         f"({round(lv)}), so the mix leans single while keeping loot for variety")
        else:
            parts.append(f"per post, loot boards ({round(lv)} views) out-perform single deals "
                         f"({round(sv)}), so the mix leans loot while keeping singles for variety")
    body = ". ".join(parts) if parts else "there isn't enough measured post data yet to summarise the week"
    return (f"{body}. (Grounded summary — the AI's own weekly narrative was withheld "
            "because some figures it cited couldn't be verified against the data.)")


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
    now = datetime.now(timezone.utc)
    recent = eng._recent_distribution(s, now)
    # Pass s/now so _weekly_plan uses the real recent-cadence median, not the stale
    # posting_frequency_baseline — kills the WeekCard's third, different posts/day.
    blueprint = eng._weekly_plan(
        bp_growth, perf, week_start, event_data, recent, s, now)["blueprint"]
    themes = blueprint.get("daily_themes") or []

    ai_summary, ai_ok = "", False
    ai_plan = None
    wk_fc_status = None
    try:
        from src.ai.client import AIUnavailable
        from src.ai.planner import generate_week_plan
        try:
            res = generate_week_plan(s, week_start, directive=directive, end_day=week_end)
            ai_summary = res.get("digest") or "" if res.get("available") else ""
            ai_ok = bool(ai_summary)
            if res.get("available"):
                ai_plan = res.get("plan")
            # FIX 2 (weekly) — same prose fact-check gate as the daily path. The
            # weekly digest doubles as the operator's weekly retro and renders in
            # the UI; a `failed` check means it likely cites a fabricated number,
            # so never surface it as trusted. The plan's own DECISIONS
            # (loot_deal_ratio/merchant_priorities/daily_themes) are structural and
            # still merged below — only the narrative prose is withheld.
            wk_fc_status = (res.get("factcheck") or {}).get("status")
            if wk_fc_status == "failed":
                # Only a `failed` check (a SUBSTANTIAL fraction unverified => likely a
                # fabricated %/MoM/mislabelled-velocity figure) withholds the narrative
                # in favour of the honest grounded summary. A `warn` is a small minority
                # unverified — per check_cited_numbers' own contract, "a mostly-grounded
                # plan is safe to act on" (usually a rounding artifact or clock-hour
                # token) — so we SHOW the AI narrative, with the FE's amber "some numbers
                # couldn't be verified" caveat. This matches the daily path (which also
                # only falls back on `failed`); withholding on `warn` too meant the
                # operator effectively never saw a weekly narrative.
                ai_summary = _grounded_weekly_summary(s, end_day=week_end)
        except AIUnavailable:
            ai_summary = ""
    except Exception:
        ai_summary = ""

    if ai_plan:
        # G1 — the whole point of running the weekly AI is its read of last week's
        # evidence (loot_deal_ratio, merchant_priorities, the per-day split); keep
        # the deterministic engine's skeleton (posts_per_day, posting_windows,
        # deal_type_allocation) for the rest, but let the AI's numbers survive into
        # what's PERSISTED — previously only `blueprint` (the deterministic-only
        # output) was stored, so `_current_week_plan`'s THIS_WEEK_DIRECTION always
        # read empty (data_flow.md G1).
        blueprint["loot_deal_ratio"] = ai_plan.get("loot_deal_ratio")
        blueprint["merchant_priorities"] = ai_plan.get("merchant_priorities")
        blueprint["direction"] = ai_plan.get("direction")
        if ai_plan.get("daily_themes"):
            blueprint["daily_themes"] = ai_plan["daily_themes"]
        # Deterministic loot/single split from per-post performance. gpt-5-mini does
        # NOT reliably follow the "rank by avg_views_per_post" instruction — it kept
        # returning a loot-heavy ratio off the confounded per-day velocity, which
        # contradicts the daily plan (the weekly↔daily conflict). Compute the split
        # from the honest per-post averages (proportional, clamped to a 30% floor so
        # both types keep variety) and override the model's ratio AND the per-day
        # shares, so the weekly direction and the daily plan agree and lean the
        # correct way (single currently out-performs loot per post: 781 vs 573).
        _pp = {p["post_type"]: (p.get("avg_views") or 0.0) for p in ctx.post_type_performance(s)}
        _lv, _sv = _pp.get("loot_deal", 0.0), _pp.get("single_deal", 0.0)
        if _lv or _sv:
            _ls = min(max(_lv / (_lv + _sv), 0.3), 0.7) if (_lv + _sv) else 0.4
            blueprint["loot_deal_ratio"] = {"loot": round(_ls * 100), "deal": round((1 - _ls) * 100)}
            for _t in (blueprint.get("daily_themes") or []):
                if isinstance(_t, dict):
                    _t["loot_share"], _t["single_share"] = round(_ls, 3), round(1 - _ls, 3)
        themes = blueprint.get("daily_themes") or []

    # Weekly EXCLUSION steer: the week is direction-level (no per-post slots to pin), but
    # an "avoid <merchant>" ask CAN be honored by dropping that merchant from the persisted
    # merchant_priorities the daily planner reads as THIS_WEEK_DIRECTION — so the week's
    # daily plans stop featuring it. Price/quantity/time have no weekly analogue (no slots).
    if directive:
        from src.services.generation.directives import parse_directive_constraints
        _avail_m = sorted({d.get("merchant_key") for d in ctx.available_deals(s, limit=40)
                           if d.get("merchant_key")})
        _wex = parse_directive_constraints(directive, _avail_m, None).get("exclude_merchants")
        if _wex and blueprint.get("merchant_priorities"):
            blueprint["merchant_priorities"] = [
                m for m in blueprint["merchant_priorities"]
                if (m.get("merchant") if isinstance(m, dict) else m) not in _wex]

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
    if wk is not None and wk_fc_status is not None:
        wk.factcheck_status = wk_fc_status
    return ai_summary, ai_ok, themes, wk


def ensure_weekly_ai_plan(s, week_start, week_end, directive: str | None = None):
    """Generate + persist this week's weekly plan through the SAME merge path the
    dashboard uses (`_weekly_ai_generate`), so the scheduled weekly job and the brief
    can never persist differently-shaped blueprints. Ensures the AI's loot_deal_ratio/
    merchant_priorities/daily_themes survive into the stored row (data_flow.md G1) —
    the scheduled job used to persist the raw AI plan directly, bypassing the merge."""
    from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan, PlanType

    wk = s.scalars(
        select(CampaignPlan)
        .where(CampaignPlan.campaign_version == CAMPAIGN_VERSION,
               CampaignPlan.plan_type == PlanType.WEEKLY,
               CampaignPlan.target_date == week_start)
        .order_by(CampaignPlan.generated_at.desc())
    ).first()
    _summary, _ok, _themes, wk = _weekly_ai_generate(s, week_start, week_end, wk, directive=directive)
    return wk


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

        # TRAILING 7-day window ENDING at `anchor` (the latest day with data / today) —
        # "the last week up to today", so the card shows real recent activity instead of
        # a Mon->Sun calendar week that runs into empty future days early in the week.
        week_end = anchor
        week_start = anchor - timedelta(days=6)

        traj = ctx.posting_trajectory(s, days=7, end_day=week_end)
        # Per-day follower deltas are intentionally NOT surfaced here: Telegram exposes
        # only the live subscriber count (no history), so joined/left/net can't be
        # captured reliably day-by-day. Posts/views below are real per-day.
        days = [{"date": d["date"],
                 "weekday": date_cls.fromisoformat(d["date"]).strftime("%a"),
                 "posts": d["posts"], "views_avg": d["views_avg"],
                 # Posts keep accruing views until ~day 4 (measured curve: day0 ~35%,
                 # day1 ~65%, day2 ~85%, day3 ~90%, day4+ settled), so the last ~3 days'
                 # avg understates and must NOT be read as a performance dip vs older,
                 # fully-matured days. Flag for the UI. ponytail: 3-day cutoff from the
                 # current maturation curve; revisit if view velocity changes.
                 "views_maturing": (week_end - date_cls.fromisoformat(d["date"])).days <= 3}
                for d in traj["days"]]
        posts_total = sum(d["posts"] for d in traj["days"])
        # true sum of daily view totals (not posts x rounded-avg, which drifts)
        views_total = round(sum(d.get("views", d["posts"] * d["views_avg"]) for d in traj["days"]))
        # Average over days you ACTUALLY posted, not a hardcoded 7 — a mid-week or
        # partial week (zero-post days included) otherwise deflates the figure and
        # renders a fractional "posts/day" that contradicts the active-day cadence
        # shown right beside it. Matches recent_cadence's active-day definition.
        active_days = sum(1 for d in traj["days"] if d["posts"] > 0)
        totals = {"posts": posts_total, "views_total": views_total,
                  "avg_posts_per_day": round(posts_total / active_days, 1) if active_days else 0.0}

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

        _bp = (wk.blueprint or {}) if wk is not None else {}
        return {"available": True,
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "days": days, "totals": totals, "themes": themes,
                # The weekly PLAN's strategic recommendations (what guides the daily
                # plans): this week's one-line direction, the loot/single target, and
                # which merchants to feature. Surfaced so the weekly page shows the
                # strategy, not just the retro + data.
                "direction": _bp.get("direction"),
                "loot_deal_ratio": _bp.get("loot_deal_ratio"),
                "merchant_priorities": _bp.get("merchant_priorities") or [],
                # Match the blueprint / daily-themes / daily-plan count (the 14-day
                # median) instead of a separate this-week trajectory, so the card's
                # "Recommended/day" agrees with the 38 shown everywhere else.
                "recommended_posts_per_day": (((wk.blueprint or {}).get("posts_per_day")
                                               if wk is not None else None)
                                              or traj["recent_cadence"]),
                "upcoming_events": evs_out, "digest": ai_summary, "ai_available": ai_ok,
                "factcheck_status": (wk.factcheck_status if wk is not None else None),
                "operator_directive": wk.operator_directive if wk is not None else None,
                # Regenerable only while this is the CURRENT trailing window (its end is
                # within the last 7 days) — matches regenerate_weekly's guard.
                "can_regenerate": week_end >= ist_today() - timedelta(days=6)}


def _past_future_split(slots, now_min):
    """Split a plan's slots into (already-elapsed, still-upcoming) by an IST
    minute-of-day cutoff. now_min=None (not today) -> everything is upcoming."""
    from src.ai.planner import _slot_minute
    past, future = [], []
    for sl in slots or []:
        m = _slot_minute(sl)
        (past if (now_min is not None and m is not None and m < now_min) else future).append(sl)
    return past, future


def _splice_past_over(past, fresh, now_min, recommended=None):
    """Keep the already-posted PAST slots and take the FRESH plan's FUTURE slots, in
    chronological order — so a mid-day steer rewrites only the remaining day and never
    posts that already went out (they are immutable — already live in ScheduledPost).

    CAPPED to ``recommended``: a mid-day regen's fresh plan carries a FULL day's slots,
    all timed after "now" (the AI was told to plan the remaining day). Without a cap the
    splice ADDS those onto the already-posted past slots — e.g. 26 posted + 41 fresh = 67
    slots crammed into the evening (a real bug). Keep the past (immutable) and only as
    many fresh future slots as the recommended total leaves room for, re-spread evenly
    across [now, end-of-day] so they never stack one-per-minute. ``recommended=None``
    keeps the old uncapped behaviour (callers that don't know the target)."""
    from src.ai.planner import _slot_minute
    _, fresh_future = _past_future_split(fresh, now_min)
    fresh_future = sorted(fresh_future, key=lambda x: (_slot_minute(x) is None, _slot_minute(x) or 0))
    if recommended is not None:
        room = max(int(recommended) - len(past), 0)
        fresh_future = fresh_future[:room]
        if fresh_future and now_min is not None:
            # Even, off-grid spread across the remaining window (reuses the same placement
            # the hard-time-window steer uses) so the kept slots don't collide into a
            # 1/min pile. Only on the capped path — recommended=None keeps AI-chosen times.
            from src.services.generation.ai_execution import _ACTIVE_END_MIN, _place_in_window
            _place_in_window(fresh_future, now_min, _ACTIVE_END_MIN)
    return sorted(list(past) + fresh_future,
                  key=lambda x: (_slot_minute(x) is None, _slot_minute(x) or 0))


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
    from src.services.generation.directives import parse_pause

    # A PAUSE request is not a content steer — steering reshapes the plan but cannot stop
    # the live queue, and auto-cancelling queued posts from free-text would be destructive
    # on a misparse. So recognize it and answer honestly, leaving the existing plan intact.
    if directive and parse_pause(directive):
        return {"available": False, "paused_intent": True,
                "reason": "This reads as a request to PAUSE posting. Steering reshapes the "
                          "plan but doesn't stop the queue, so I left your current plan "
                          "unchanged rather than regenerating it. To actually pause, clear "
                          "today's queued posts or turn off the scheduler. If you meant a "
                          "posting change (merchants, timing, mix, price), tell me that and "
                          "I'll steer it."}

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

        # Load the current plan (for the pre-steer snapshot + mid-day freeze below). Each
        # steer is independent now, so we do NOT accumulate a steering history.
        old = s.scalar(select(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.DAILY,
            CampaignPlan.target_date == day).order_by(CampaignPlan.generated_at.desc()))
        # Snapshot the old plan (all cols but id) so we can RESTORE it if regeneration
        # fails — otherwise a failed regen (e.g. AI at quota) destroys the good plan.
        old_snap = ({c.name: getattr(old, c.name) for c in CampaignPlan.__table__.columns
                     if c.name != "id"} if old is not None else None)
        # A JSON-safe snapshot of the PRE-steer plan, stored on the new row so the operator
        # can REVERT to exactly this plan (no regeneration, no AI cost). Only the display/
        # restore fields (all JSON-safe); target_date/plan_type/version are constants on
        # rebuild, generated_at is stamped fresh. The nested blueprint's own `_pre_steer` is
        # stripped so undo is one level deep and snapshots can't nest unboundedly.
        pre_steer_snap = None
        if old is not None:
            _obp = {k: v for k, v in (old.blueprint or {}).items() if k != "_pre_steer"}
            pre_steer_snap = {
                "title": old.title, "blueprint": _obp,
                "expected_outcome": old.expected_outcome, "confidence": old.confidence,
                "is_ai_generated": old.is_ai_generated, "ai_digest": old.ai_digest,
                "cited_numbers": old.cited_numbers, "factcheck_status": old.factcheck_status,
                "report_ids": old.report_ids, "operator_directive": old.operator_directive}
        # For a mid-day steer of TODAY, freeze what already went out: slots whose IST
        # time has passed are already posted (immutable). Capture them so (a) the AI is
        # told not to replan them, and (b) we splice them back over the fresh plan so a
        # steer rewrites only the REMAINING day.
        from datetime import datetime as _dt, timezone as _tz
        from src.services.analytics.periods import to_ist
        _now_ist = to_ist(_dt.now(_tz.utc))
        now_min = (_now_ist.hour * 60 + _now_ist.minute) if day == ist_today() else None
        past_slots, _ = _past_future_split((old.blueprint or {}).get("post_slots") if old else [], now_min)
        s.execute(delete(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.DAILY,
            CampaignPlan.target_date == day,
        ))

    # Each steer is INDEPENDENT: the plan is restructured from THIS directive ALONE, never
    # an accumulation of past asks. Accumulating them made an old, unrelated steer (e.g.
    # "deals under ₹1000") keep re-applying to a new one (e.g. "make it 30"). Both the
    # prompt AND the hard-constraint parsing now see ONLY the latest directive; to combine
    # asks the operator writes one combined directive.
    composed = directive
    # The desired post count from the RAW latest ask (not the composed blob below, which
    # carries "N posts already live"). Threaded as the target cadence + used for the note.
    from src.services.generation.directives import parse_target_posts
    _target = parse_target_posts(directive)
    # Mid-day you can't un-send what already went out, so a request to REDUCE below the
    # already-posted count can't be honored today — say so plainly instead of showing a
    # lower headline over a higher real count.
    if _target and past_slots and _target < len(past_slots):
        composed = (composed or "") + (
            f"\n\nNOTE: {len(past_slots)} posts already went out today — MORE than the {_target} "
            f"requested, and they can't be un-sent. State plainly that today already exceeded "
            f"{_target}; the lower count applies to FUTURE days, not retroactively.")
    # Tell the AI what already went out today so it plans the REST of the day coherently
    # (doesn't re-suggest a merchant/theme just used, and knows how many slots remain)
    # rather than replanning the whole day blind.
    if past_slots:
        _posted = "; ".join(f"{sl.get('time_ist')} {sl.get('type')} {sl.get('merchant')}/{sl.get('theme')}"
                            for sl in past_slots[:40])
        composed = (composed or directive or "") + (
            f"\n\nALREADY POSTED TODAY — {len(past_slots)} posts are already live and CANNOT change: "
            f"{_posted}.\nPlan ONLY the remaining slots for AFTER {_now_ist.strftime('%H:%M')} IST today; "
            "do not replan the posts above. In your narrative, briefly acknowledge that these "
            "already went out and can't be changed. If my request only affects times/windows that "
            "have ALREADY passed today (e.g. asking to change the morning when it's afternoon), say "
            "so plainly — there's nothing left to reschedule for that window today.")
    result = daily_brief(date=day.isoformat(), directive=composed, target_posts=_target)
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
            # Each steer stands alone now (no steering_history accumulation) — operator_directive
            # is just the latest raw ask, which is what the FE shows as "Steered by".
            _bp = {**(row.blueprint or {})}
            # Stash the pre-steer plan so a "Revert" restores it exactly (one level of undo).
            if pre_steer_snap is not None:
                _bp["_pre_steer"] = pre_steer_snap
            # Splice the already-posted PAST slots back over the fresh plan: a mid-day
            # steer only rewrites the remaining day; posts that already went out stay
            # exactly as they were. Also reflect it in the response the UI renders now.
            if past_slots:
                _spliced = _splice_past_over(past_slots, _bp.get("post_slots") or [], now_min,
                                             recommended=_bp.get("recommended_posts"))
                _bp["post_slots"] = _spliced
                # Honesty: if the steer produced NO new future slots (e.g. it targeted a
                # window that's already elapsed today), the spliced plan is just what
                # already posted — say so plainly instead of silently returning an
                # unchanged plan. `_splice_past_over` returns the SAME past objects, so a
                # slot not among them by identity is genuinely new/future.
                _past_ids = {id(p) for p in past_slots}
                if not any(id(sl) not in _past_ids for sl in _spliced):
                    _note = ("Your steer only affects times that have already passed today, so "
                             "there's nothing left to reschedule — the posts above already went "
                             "out and can't change. Regenerate for a future day, or steer a later "
                             "window, to apply it.")
                    _bp["watch"] = ((_bp.get("watch") or "") + " " + _note).strip()
                    if result.get("today"):
                        result["today"]["watch"] = _bp["watch"]
                if result.get("today"):
                    result["today"]["slots"] = _spliced
            row.blueprint = _bp
            row.operator_directive = directive
            # Surface the RAW operator ask, not the composed blob (history + the
            # already-posted context) that daily_brief persisted as it generated.
            result["operator_directive"] = directive
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


def revert_daily(date: str | None = None) -> dict:
    """Undo the last steer/regenerate for ``date`` — restore the plan that existed BEFORE
    it, from the snapshot `regenerate_daily` stashed under blueprint._pre_steer. No AI call:
    it rebuilds the exact prior row. One level of undo. Refuses when there's no snapshot (the
    day was never steered) or the day has already elapsed."""
    from datetime import date as date_cls, datetime, timezone
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
                    "reason": "This day has already elapsed — reverting it has no effect."}
        cur = s.scalar(select(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.DAILY,
            CampaignPlan.target_date == day).order_by(CampaignPlan.generated_at.desc()))
        snap = (cur.blueprint or {}).get("_pre_steer") if cur is not None else None
        if not snap:
            return {"available": False,
                    "reason": "No earlier plan to revert to — this day hasn't been steered."}
        # Replace the current steered row with an exact rebuild of the pre-steer one.
        s.execute(delete(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.DAILY,
            CampaignPlan.target_date == day))
        s.add(CampaignPlan(
            plan_type=PlanType.DAILY, campaign_version=CAMPAIGN_VERSION,
            target_date=day, generated_at=datetime.now(timezone.utc),
            title=snap.get("title") or f"AI day plan {day.isoformat()}",
            blueprint=snap.get("blueprint") or {},
            expected_outcome=snap.get("expected_outcome"),
            confidence=snap.get("confidence"),
            is_ai_generated=bool(snap.get("is_ai_generated")),
            ai_digest=snap.get("ai_digest") or "",
            cited_numbers=snap.get("cited_numbers") or [],
            factcheck_status=snap.get("factcheck_status"),
            report_ids=snap.get("report_ids") or [],
            operator_directive=snap.get("operator_directive")))
        record_ai_output("plan_reverted",
                         f"daily {day.isoformat()} — reverted to pre-steer plan",
                         get_settings().ai_model)
    return daily_brief(date=day.isoformat())


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
    from src.services.generation.directives import parse_pause

    if directive and parse_pause(directive):
        return {"available": False, "paused_intent": True,
                "reason": "This reads as a request to PAUSE posting, which steering can't do "
                          "— it reshapes the plan but doesn't stop the queue. Your weekly plan "
                          "was left unchanged. To pause, clear the queue or turn off the "
                          "scheduler; for a posting change, tell me the merchants/mix to steer."}

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

        # Trailing 7-day window ending at the anchor. Only the CURRENT window (anchor
        # within the last 7 days) is regenerable — an old historical anchor is elapsed.
        if anchor < ist_today() - timedelta(days=6):
            return {"available": False,
                    "reason": "This week has already elapsed — regenerating it has no effect."}
        week_end = anchor
        week_start = anchor - timedelta(days=6)

        # Snapshot the old weekly row (all cols but id) BEFORE deleting, so a failed
        # regen (AI at quota) can be rolled back instead of blanking the week — the
        # same restore-on-failure guard the daily path has.
        old = s.scalar(select(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.WEEKLY,
            CampaignPlan.target_date == week_start).order_by(CampaignPlan.generated_at.desc()))
        old_snap = ({c.name: getattr(old, c.name) for c in CampaignPlan.__table__.columns
                     if c.name != "id"} if old is not None else None)

        s.execute(delete(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.WEEKLY,
            CampaignPlan.target_date == week_start,
        ))

    # Pass the anchor (window END) so weekly_brief re-derives the SAME trailing window.
    result = weekly_brief(end=week_end.isoformat(), directive=directive)
    # Success = an AI-generated weekly row actually landed. weekly_brief still persists a
    # deterministic (is_ai_generated=False) blueprint row when the AI is down, so checking
    # is_ai_generated (not just row-exists) is what distinguishes a real regen from a
    # silent fallback that would otherwise replace the good narrative.
    restored = False
    with session_scope() as s2:
        row = s2.scalar(select(CampaignPlan).where(
            CampaignPlan.campaign_version == CAMPAIGN_VERSION,
            CampaignPlan.plan_type == PlanType.WEEKLY,
            CampaignPlan.target_date == week_start,
            CampaignPlan.is_ai_generated == True).order_by(CampaignPlan.generated_at.desc()))  # noqa: E712
        if row is None and old_snap is not None:
            # Drop the deterministic stand-in the failed regen left, restore the prior good row.
            s2.execute(delete(CampaignPlan).where(
                CampaignPlan.campaign_version == CAMPAIGN_VERSION,
                CampaignPlan.plan_type == PlanType.WEEKLY,
                CampaignPlan.target_date == week_start))
            s2.add(CampaignPlan(**old_snap))
            restored = True
    if restored:
        return {"available": False, "restored": True,
                "reason": f"Regeneration failed ({result.get('reason') or 'AI unavailable'}) "
                          "— kept your existing weekly plan."}
    if result.get("available"):
        note = f"weekly {week_start.isoformat()} — directive: {directive[:200] if directive else '(none)'}"
        record_ai_output("plan_regenerated", note, get_settings().ai_model)
    return result


def queue(page: int = 1, page_size: int = 20, date: str | None = None,
          post_type: str | None = None, status: str | None = None,
          sort: str = "soonest") -> dict:
    """Posting schedule, filterable + sortable (all state comes from URL params on the FE).

    - ``date``: IST day (YYYY-MM-DD) — rows whose fire time falls on that IST day.
    - ``post_type``: 'single' | 'loot' (loot = the post_type carries 'loot'/'collection').
    - ``status``: one ScheduledPost status (queued/sending/published/blocked/…).
    - ``sort``: 'newest' (default, latest fire first) | 'oldest'.

    `counts` reflects the date+type scope (so the status chips stay a drill-in breakdown);
    `total` (pagination) reflects every filter including status.
    """
    from datetime import date as _date_cls, datetime, timezone
    from sqlalchemy import or_
    from src.services.analytics.periods import ist_day_bounds_utc
    page, page_size, offset = _clamp_page(page, page_size)
    join_gp = post_type in ("single", "loot")
    scope = []  # date + type conditions — the "what am I looking at" view
    if date:
        try:
            lo, hi = ist_day_bounds_utc(_date_cls.fromisoformat(date))
            scope += [ScheduledPost.scheduled_at >= lo.replace(tzinfo=None),
                      ScheduledPost.scheduled_at < hi.replace(tzinfo=None)]
        except (ValueError, TypeError):
            pass
    if join_gp:
        loot = or_(GeneratedPost.post_type.ilike("%loot%"),
                   GeneratedPost.post_type.ilike("%collection%"))
        scope.append(loot if post_type == "loot" else ~loot)

    def scoped(sel):
        if join_gp:
            sel = sel.join(GeneratedPost, ScheduledPost.generated_post_id == GeneratedPost.id)
        for c in scope:
            sel = sel.where(c)
        return sel

    with session_scope() as s:
        counts = dict(s.execute(
            scoped(select(ScheduledPost.status, func.count()))
            .group_by(ScheduledPost.status)).all())
        cnt_sel = scoped(select(func.count()).select_from(ScheduledPost))
        row_sel = scoped(select(ScheduledPost))
        if status:
            cnt_sel = cnt_sel.where(ScheduledPost.status == status)
            row_sel = row_sel.where(ScheduledPost.status == status)
        total = s.scalar(cnt_sel) or 0
        # a posting schedule reads best soonest-first (the next post to fire at the top),
        # so ascending is the default; only an explicit "latest" flips to furthest-first.
        # Vocabulary is exactly {soonest (default), latest} — no newest/oldest aliases.
        descending = sort == "latest"
        order = (ScheduledPost.scheduled_at.desc() if descending
                 else ScheduledPost.scheduled_at.asc())
        rows = s.scalars(row_sel.order_by(order).offset(offset).limit(page_size)).all()
        # a post is OVERDUE if its fire time has passed but it hasn't been delivered
        # (still queued/sending/retry) — i.e. it should have gone out and didn't.
        _now = datetime.now(timezone.utc).replace(tzinfo=None)
        _pending = {ScheduleStatus.QUEUED, ScheduleStatus.SENDING, ScheduleStatus.RETRY}
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
                "rationale": gp.strategy_rationale if gp is not None else None,
                "status": r.status,
                "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
                "overdue": bool(r.scheduled_at and r.status in _pending
                                and r.scheduled_at < _now),
                "attempts": f"{r.attempts}/{r.max_attempts}",
                "note": (r.last_error or "")})
    return {"counts": counts, "items": items, **_page_meta(total, page, page_size)}


def activity_recent(since: str | None = None, limit: int = 20) -> dict:
    """Recent real events — drafts written, posts sent/blocked, scheduler jobs
    completed — merged into one feed, newest first. Not a new data source: a
    union+sort over GeneratedPost/ScheduledPost/SchedulerRun, the same tables
    `queue()`/`drafts()`/`scheduler_runs()` already read. Powers the live
    activity toast stream and the Overview "since you were last here" digest.
    """
    from datetime import datetime, timezone
    from src.db.models_scheduler import SchedulerRun

    cutoff = None
    if since:
        try:
            cutoff = datetime.fromisoformat(since.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            cutoff = None

    events: list[dict] = []
    with session_scope() as s:
        gp_q = select(GeneratedPost).order_by(GeneratedPost.generated_at.desc()).limit(limit)
        if cutoff:
            gp_q = gp_q.where(GeneratedPost.generated_at > cutoff)
        for gp in s.scalars(gp_q):
            facts = _post_facts(gp)
            events.append({
                "type": "draft_created",
                "at": gp.generated_at.isoformat() if gp.generated_at else None,
                "label": f"Drafted a post — {facts['merchant'] or 'mixed'}, {gp.post_type or 'post'}",
                "ref_id": gp.id,
            })

        sp_pub_q = (select(ScheduledPost)
                    .where(ScheduledPost.status == ScheduleStatus.PUBLISHED,
                           ScheduledPost.published_at.isnot(None))
                    .order_by(ScheduledPost.published_at.desc()).limit(limit))
        if cutoff:
            sp_pub_q = sp_pub_q.where(ScheduledPost.published_at > cutoff)
        for sp in s.scalars(sp_pub_q):
            events.append({
                "type": "post_published", "at": sp.published_at.isoformat(),
                "label": f"Sent to {sp.channel_ref}", "ref_id": sp.generated_post_id,
            })

        sp_blk_q = (select(ScheduledPost)
                    .where(ScheduledPost.status == ScheduleStatus.BLOCKED)
                    .order_by(ScheduledPost.updated_at.desc()).limit(limit))
        if cutoff:
            sp_blk_q = sp_blk_q.where(ScheduledPost.updated_at > cutoff)
        for sp in s.scalars(sp_blk_q):
            events.append({
                "type": "post_blocked",
                "at": sp.updated_at.isoformat() if sp.updated_at else None,
                "label": f"Blocked — {(sp.last_error or 'no reason recorded')[:80]}",
                "ref_id": sp.generated_post_id,
            })

        job_q = (select(SchedulerRun).where(SchedulerRun.ended_at.isnot(None))
                 .order_by(SchedulerRun.ended_at.desc()).limit(limit))
        if cutoff:
            job_q = job_q.where(SchedulerRun.ended_at > cutoff)
        for r in s.scalars(job_q):
            events.append({
                "type": "job_run", "at": r.ended_at.isoformat(),
                "label": f"{r.scheduler_key} — {r.status}", "ref_id": None,
            })

    events.sort(key=lambda e: e["at"] or "", reverse=True)
    return {"events": events[:limit], "server_time": datetime.now(timezone.utc).isoformat()}


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
