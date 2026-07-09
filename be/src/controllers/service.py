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


def competitors() -> dict:
    with session_scope() as s:
        return {
            "profiles": ctx.competitor_profiles(s),
        }


def competitor_dashboard(window_days: int | None = None) -> dict:
    """Unified competitor dashboard — profiles + benchmarks, grouped by category.

    ``window_days`` when set filters basic stats to the last N days (like comparison).
    """
    from src.services.analytics import comparison as cmp
    from src.db.models_competitor_intel import (
        CompetitorProfile, CompetitorBenchmark,
        COMPETITOR_INTEL_VERSION,
    )

    with session_scope() as s:
        # comparison data (owned + competitors with profiles)
        comp = cmp.compare(s, window_days=window_days)
        entities = comp.get("entities", [])

        # raw DB rows for category + benchmark access
        competitors_raw = {
            c.id: c for c in s.scalars(select(Competitor)).all()
        }
        profiles_raw = {
            p.competitor_id: p for p in s.scalars(
                select(CompetitorProfile).where(
                    CompetitorProfile.intel_version == COMPETITOR_INTEL_VERSION)
            ).all()
        }

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
        if plan:
            weekly = {"title": plan.title, "blueprint": plan.blueprint,
                      "expected_outcome": plan.expected_outcome, "confidence": plan.confidence,
                      "generated_at": plan.generated_at.isoformat() if plan.generated_at else None}
        reasoning = ctx.reasoning_insights(s)
        recs = ctx.growth_recommendations(s, limit=6)

    ai_summary = None
    if include_ai:
        try:
            from src.ai.briefing import BriefingGenerator
            from src.ai.client import AIUnavailable
            try:
                ai_summary = BriefingGenerator().generate(weekly=True)
            except AIUnavailable:
                ai_summary = None
        except Exception:  # briefing is best-effort; never break the report
            ai_summary = None

    return {"available": weekly is not None, "weekly_plan": weekly,
            "what_changed": reasoning, "recommendations": recs, "ai_summary": ai_summary}


def _plan_date_bounds(s):
    from src.services.analytics.periods import IST, owned_window
    w = owned_window(s)
    mn = w["start"].astimezone(IST).date() if w.get("start") else None
    mx = w["end"].astimezone(IST).date() if w.get("end") else None
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
    raw = bp.get("posting_plan") or []
    raw_sum = sum((p.get("recommended_posts_per_day") or 0) for p in raw) or 1
    windows = [{"part": p.get("part"), "hours": p.get("hours"),
                "posts": round((p.get("recommended_posts_per_day") or 0) * recommended_posts / raw_sum),
                # historical day-part performance, when known — lets the AI cite a real
                # number for WHY this window instead of generic "peak hours" filler.
                "avg_views_per_day": p.get("avg_views_per_day")}
               for p in raw]
    allocation = eng._allocate_posts(bp, recommended_posts)
    merchants = eng._merchant_allocation(s, recent, now)
    risks = eng._risks(recent, recommended_posts)
    return windows, allocation, merchants, (risks or None)


def daily_brief(date: str | None = None) -> dict:
    """The daily plan: what happened YESTERDAY + what to do TODAY, with a cadence
    recommendation grounded in the recent posting trajectory (not the stale lifetime
    baseline). AI writes the narrative + slots best-effort; the numbers are
    deterministic and fact-checked.

    The AI-authored part (digest + slots) is cached per (day, campaign version) as a
    `CampaignPlan` row: the first request for a given day calls the model and persists
    the result; every subsequent request for that SAME day reuses the stored row
    instead of re-calling the AI. A request for a different day always plans fresh."""
    from datetime import date as date_cls, timedelta
    from src.services.analytics.day import latest_owned_date
    from src.services.planning.calendar import upcoming_events
    from src.ai.planner import generate_day_plan
    from src.ai.factcheck import check_cited_numbers
    from src.db.models_campaign import PlanType
    from src.services.generation.ai_execution import persist_ai_plan

    with session_scope() as s:
        mn, mx = _plan_date_bounds(s)
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
        else:
            ai_res = generate_day_plan(s, day, inputs={
                "recommended_posts": recommended,
                "posting_windows": windows,
                "deal_type_allocation": allocation,
                "merchant_allocation": merchants,
                "upcoming_event": evt,
            })
            ai_ok = bool(ai_res.get("available"))
            plan = ai_res.get("plan") or {}
            digest = ai_res.get("digest", "") if ai_ok else ""
            fc_status = None
            if ai_ok:
                fc = check_cited_numbers(plan.get("cited_numbers", []), ai_res.get("facts", []))
                fc_status = "pass" if fc["status"] == "passed" else "warn"
                row = persist_ai_plan(s, {**ai_res, "factcheck": fc})
                if row is not None:
                    # Pin the cache key to the day we actually planned for — the
                    # AI's self-reported "date" inside the plan JSON isn't reliable
                    # enough (missing/mismatched) to key the cache lookup on.
                    row.target_date = day

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
        }


def weekly_brief(end: str | None = None) -> dict:
    """The weekly view: last 7 days of actual posting + this week's themes + an AI
    weekly narrative (best-effort)."""
    from datetime import date as date_cls
    from src.services.analytics.day import latest_owned_date
    from src.services.analytics.daily_report import _owned_channel
    from src.services.planning.calendar import upcoming_events
    from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan, PlanType

    with session_scope() as s:
        end_day = None
        if end:
            try:
                end_day = date_cls.fromisoformat(end)
            except ValueError:
                end_day = None
        if end_day is None:
            end_day = latest_owned_date(s)
        if end_day is None:
            return {"available": False, "reason": "No owned posts yet."}

        traj = ctx.posting_trajectory(s, days=7, end_day=end_day)
        ch = _owned_channel(s)
        week_start_date = date_cls.fromisoformat(traj["days"][0]["date"]) if traj["days"] else end_day
        deltas = ctx.follower_deltas_by_day(s, ch.id if ch else None, week_start_date, end_day)
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
                             CampaignPlan.plan_type == PlanType.WEEKLY)
                      .order_by(CampaignPlan.generated_at.desc()))
        themes = ((wk.blueprint or {}).get("daily_themes") if wk else None) or []

        evs_out = []
        try:
            for e in upcoming_events(s, end_day, within_days=30)[:3]:
                evs_out.append({"name": e.name, "date": e.next_date.isoformat(),
                                "days_away": (e.next_date - end_day).days,
                                "date_confidence": e.date_confidence})
        except Exception:
            pass

        ai_summary, ai_ok = "", False
        try:
            from src.ai.briefing import BriefingGenerator
            from src.ai.client import AIUnavailable
            try:
                ai_summary = BriefingGenerator().generate(weekly=True) or ""
                ai_ok = bool(ai_summary)
            except AIUnavailable:
                ai_summary = ""
        except Exception:
            ai_summary = ""

        if ai_ok and wk is not None:
            wk.ai_digest = ai_summary
            wk.is_ai_generated = True

        return {"available": True,
                "week_start": traj["days"][0]["date"] if traj["days"] else end_day.isoformat(),
                "week_end": end_day.isoformat(),
                "days": days, "totals": totals, "themes": themes,
                "recommended_posts_per_day": traj["recent_cadence"],
                "upcoming_events": evs_out, "digest": ai_summary, "ai_available": ai_ok}


def queue(page: int = 1, page_size: int = 20) -> dict:
    page, page_size, offset = _clamp_page(page, page_size)
    with session_scope() as s:
        counts = dict(s.execute(
            select(ScheduledPost.status, func.count()).group_by(ScheduledPost.status)).all())
        total = s.scalar(select(func.count()).select_from(ScheduledPost)) or 0
        rows = s.scalars(select(ScheduledPost)
                         .order_by(ScheduledPost.scheduled_at)
                         .offset(offset).limit(page_size)).all()
        # attach each draft's category (selection_bucket) so the day-plan is legible
        cats = {}
        pids = [r.generated_post_id for r in rows if r.generated_post_id]
        if pids:
            for gp in s.scalars(select(GeneratedPost).where(GeneratedPost.id.in_(pids))):
                cats[gp.id] = gp.selection_bucket
        items = [{"id": r.id, "post_id": r.generated_post_id, "channel": r.channel_ref,
                  "category": cats.get(r.generated_post_id),
                  "status": r.status,
                  "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
                  "attempts": f"{r.attempts}/{r.max_attempts}",
                  "note": (r.last_error or "")} for r in rows]
    return {"counts": counts, "items": items, **_page_meta(total, page, page_size)}
