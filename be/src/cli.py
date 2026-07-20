"""Command-line orchestrator for the Data Collection Engine (Phase 1).

Everything the operator can do today lives here: initialise storage, authorise
the Telegram session once, run any collector on demand, run the scheduler, and
inspect job/collection status. No analytics/AI/UI commands exist — by design.
"""

from __future__ import annotations

import time

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select

import src as _pkg
from src.services.collection.affiliate import AffiliateLinkCollector
from src.services.collection.base import JobRunner
from src.services.collection.merchant import MerchantEnrichmentCollector
from src.services.collection.merchants.registry import seed_merchants
from src.services.collection.telegram_competitor import CompetitorCollector
from src.services.collection.telegram_owned import OwnedChannelCollector
from src.config.settings import get_settings
from src.db.models import (
    Channel,
    CollectionJob,
    Competitor,
    CompetitorPost,
    CollectionType,
    Merchant,
    MerchantProduct,
    Post,
    SourceAccessStatus,
)
from src.db.session import init_db, session_scope
from src.logger import setup_logging

app = typer.Typer(add_completion=False, help="Telegram Growth & Intelligence — Phase 1 (Data Foundation)")
console = Console()


@app.callback()
def _main() -> None:
    setup_logging(get_settings().log_level)


@app.command("init-db")
def init_db_cmd() -> None:
    """Create all tables, seed the merchant registry + default org (idempotent)."""
    from src.db.org_seed import seed_org

    init_db()
    with session_scope() as s:
        changed = seed_merchants(s)
        org = seed_org(s)
    console.print(f"[green]Storage initialised.[/green] Merchant registry: {changed} new rows. "
                  f"Org: {org.name} ({org.key}).")


@app.command("create-user")
def create_user_cmd(
    email: str = typer.Argument(..., help="Login email"),
    name: str = typer.Option(None, help="Display name"),
    role: str = typer.Option("editor", help="owner | editor | viewer"),
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
) -> None:
    """Create a dashboard login for the default org."""
    from src.controllers.accounts import create_user
    from src.db.org_seed import get_default_org

    with session_scope() as s:
        org = get_default_org(s)
        if org is None:
            console.print("[red]No org. Run `tgagent seed-org` first.[/red]")
            raise typer.Exit(1)
        res = create_user(org.id, name or email, email, password, role)
    if res.get("ok"):
        console.print(f"[green]Created user[/green] {email} ({role}).")
    else:
        console.print(f"[red]{res.get('error')}[/red]")
        raise typer.Exit(1)


@app.command("seed-org")
def seed_org_cmd() -> None:
    """Create/refresh the default organization and link existing channels to it."""
    from sqlalchemy import func

    from src.db.models import Channel
    from src.db.models_org import Organization, User
    from src.db.org_seed import seed_org

    with session_scope() as s:
        org = seed_org(s)
        s.flush()
        n_ch = s.scalar(select(func.count()).select_from(Channel).where(Channel.org_id == org.id))
        n_users = s.scalar(select(func.count()).select_from(User).where(User.org_id == org.id))
    console.print(f"[green]Org ready:[/green] {org.name} ({org.key}) · provider="
                  f"{org.affiliate_provider} · {n_ch} channel(s) · {n_users} user(s).")


@app.command("doctor")
def doctor() -> None:
    """Report configuration + which data sources are actually available."""
    s = get_settings()
    table = Table(title=f"tgagent v{_pkg.__version__} — Phase {_pkg.__phase__}")
    table.add_column("Source")
    table.add_column("Status")
    table.add_column("Detail")

    table.add_row(
        "Telegram (owned, MTProto)",
        "[green]available[/green]" if s.telegram_available else "[yellow]unavailable[/yellow]",
        f"{len(s.owned_channels)} channel(s)" if s.telegram_available
        else "set TELEGRAM_API_ID/HASH + OWNED_CHANNELS",
    )
    table.add_row(
        "Competitors (t.me/s)",
        "[green]available[/green]" if s.competitors_available else "[yellow]unavailable[/yellow]",
        f"{len(s.competitor_channels)} channel(s)" if s.competitors_available
        else "set COMPETITOR_CHANNELS",
    )
    table.add_row(
        "Amazon Creators API",
        "[green]creds set[/green]" if s.amazon_available else "[yellow]no creds[/yellow]",
        "request contract still requires verification (RULE 5)",
    )
    table.add_row(
        "Flipkart Affiliate API",
        "[green]creds set[/green]" if s.flipkart_available else "[yellow]no creds[/yellow]",
        "request contract still requires verification (RULE 5)",
    )
    table.add_row("boAt (Shopify JSON)", "[green]available[/green]", "no credentials needed")
    table.add_row("Reliance Digital (HTTP)", "[green]partial[/green]", "raw stored; selectors unverified")
    table.add_row("DB", "[cyan]configured[/cyan]", s.db_url)
    console.print(table)


@app.command("telegram-login")
def telegram_login() -> None:
    """Authorise the Telethon user session once (interactive: phone + code).

    Driven through an explicit asyncio loop rather than telethon.sync — the
    .sync wrapper relies on an implicit event loop that Python 3.14 removed.
    """
    import asyncio

    s = get_settings()
    if not (s.telegram_api_id and s.telegram_api_hash):
        console.print("[red]TELEGRAM_API_ID / TELEGRAM_API_HASH not set.[/red]")
        raise typer.Exit(code=1)
    from telethon import TelegramClient

    async def _run():
        client = TelegramClient(s.telegram_session_name, s.telegram_api_id, s.telegram_api_hash)
        # start() sends the login code to the phone, then prompts for the code
        # (and 2FA password if enabled) via input()/getpass.
        await client.start(phone=s.telegram_phone or None)
        me = await client.get_me()
        await client.disconnect()
        return me

    me = asyncio.run(_run())
    console.print(f"[green]Authorised as[/green] {getattr(me, 'username', None) or me.id}")


@app.command("list-channels")
def list_channels() -> None:
    """List channels your authorised account can access.

    Broadcast channels where you are creator/admin are the valid candidates for
    OWNED_CHANNELS (full history + broadcast stats require admin). Uses the
    existing session — no interactive login.
    """
    import asyncio

    s = get_settings()
    if not (s.telegram_api_id and s.telegram_api_hash):
        console.print("[red]TELEGRAM_API_ID / TELEGRAM_API_HASH not set.[/red]")
        raise typer.Exit(code=1)
    from telethon import TelegramClient

    async def _run() -> list[dict]:
        client = TelegramClient(s.telegram_session_name, s.telegram_api_id, s.telegram_api_hash)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return []
            out: list[dict] = []
            async for dialog in client.iter_dialogs():
                ent = dialog.entity
                if not getattr(ent, "broadcast", False):
                    continue  # only broadcast channels
                creator = bool(getattr(ent, "creator", False))
                admin = creator or getattr(ent, "admin_rights", None) is not None
                out.append(
                    {
                        "title": dialog.name,
                        "username": getattr(ent, "username", None),
                        "id": ent.id,
                        "role": "creator" if creator else ("admin" if admin else "member"),
                    }
                )
            return out
        finally:
            await client.disconnect()

    channels = asyncio.run(_run())
    if not channels:
        console.print("[yellow]No session or no channels found. Run `tgagent telegram-login`.[/yellow]")
        return
    table = Table(title="Your channels (owned candidates = creator/admin)")
    for col in ("title", "username", "id", "role"):
        table.add_column(col)
    for c in channels:
        mark = "[green]" if c["role"] in ("creator", "admin") else "[dim]"
        uname = f"@{c['username']}" if c["username"] else f"-100{c['id']}"
        table.add_row(f"{mark}{c['title']}[/]", uname, str(c["id"]), c["role"])
    console.print(table)
    console.print(
        "\nSet [cyan]OWNED_CHANNELS[/cyan] in .env to the @usernames (or -100 ids) "
        "of the channels you [green]creator/admin[/green], comma-separated."
    )


@app.command("collect-owned")
def collect_owned(
    channel: str = typer.Argument(..., help="Owned channel username or -100... id"),
    initial: bool = typer.Option(False, help="Full 12-month historical backfill"),
    analytics: bool = typer.Option(False, help="Broadcast stats + metric refresh"),
) -> None:
    """Run the owned-channel collector once."""
    ctype = (
        CollectionType.ANALYTICS if analytics
        else CollectionType.INITIAL if initial
        else CollectionType.INCREMENTAL
    )
    job = JobRunner().run_collector(
        OwnedChannelCollector(channel, ctype), collection_type=ctype, target=channel
    )
    _print_job(job)


@app.command("collect-competitor")
def collect_competitor(
    username: str = typer.Argument(..., help="Public channel username (no @)"),
    pages: int = typer.Option(1, help="How many t.me/s pages to paginate"),
) -> None:
    """Run the competitor collector once."""
    job = JobRunner().run_collector(
        CompetitorCollector(username, max_pages=pages),
        collection_type=CollectionType.INCREMENTAL,
        target=username,
    )
    _print_job(job)


@app.command("enrich-merchant")
def enrich_merchant(url: str = typer.Argument(..., help="Product URL to enrich")) -> None:
    """Enrich a single product URL (buildable merchants only)."""
    job = JobRunner().run_collector(
        MerchantEnrichmentCollector(url), collection_type=CollectionType.MANUAL, target=url
    )
    _print_job(job)


@app.command("check-link")
def check_link(url: str = typer.Argument(..., help="Short/affiliate URL to resolve + check")) -> None:
    """Resolve an affiliate/short link and check whether it is broken."""
    job = JobRunner().run_collector(
        AffiliateLinkCollector(url), collection_type=CollectionType.MANUAL, target=url
    )
    _print_job(job)


@app.command("resolve-links")
def resolve_links(
    limit: int = typer.Option(300, help="How many shortlinks to resolve this run"),
    delay: float = typer.Option(0.3, help="Delay between requests (seconds)"),
) -> None:
    """Follow grbn.in/short links to their real merchant and backfill merchant data.

    Lifts merchant coverage: each resolved link reveals the merchant we couldn't
    know at normalization time. Re-run until coverage stops rising.
    """
    from sqlalchemy import func, or_, select

    from src.services.collection.link_resolution import LinkResolutionEngine
    from src.db.models_normalization import ExtractedLink

    job = JobRunner().run_collector(
        LinkResolutionEngine(limit=limit, delay=delay),
        collection_type=CollectionType.MANUAL, target="link_resolution",
    )
    _print_job(job)
    with session_scope() as s:
        total = s.scalar(select(func.count()).select_from(ExtractedLink))
        known = s.scalar(select(func.count()).select_from(ExtractedLink).where(
            ExtractedLink.merchant_key.isnot(None)))
        pending = s.scalar(select(func.count()).select_from(ExtractedLink).where(
            ExtractedLink.merchant_key.is_(None), ExtractedLink.resolved_url.is_(None),
            or_(ExtractedLink.resolution_attempts.is_(None), ExtractedLink.resolution_attempts < 5)))
    cov = (100 * known / total) if total else 0
    console.print(f"[cyan]Merchant coverage:[/cyan] {known}/{total} links ({cov:.1f}%); "
                  f"{pending} links still pending resolution.")


@app.command("normalize")
def normalize(
    owned: bool = typer.Option(True, help="Normalize owned-channel posts"),
    competitor: bool = typer.Option(True, help="Normalize competitor posts"),
) -> None:
    """Phase 2: normalize raw posts into structured entities (deterministic)."""
    from src.services.processing.normalizer import PostNormalizer

    job = JobRunner().run_collector(
        PostNormalizer(include_owned=owned, include_competitor=competitor),
        collection_type=CollectionType.MANUAL,
        target="normalize",
    )
    _print_job(job)


@app.command("normalize-status")
def normalize_status() -> None:
    """Show normalization coverage + extracted-entity counts."""
    from sqlalchemy import func, select

    from src.db.models import CompetitorPost, Post
    from src.db.models_normalization import (
        ExtractedCoupon,
        ExtractedLink,
        ExtractedPrice,
        NormalizedPost,
        SourceType,
    )

    with session_scope() as s:
        owned_total = s.scalar(select(func.count()).select_from(Post))
        comp_total = s.scalar(select(func.count()).select_from(CompetitorPost))
        norm_owned = s.scalar(
            select(func.count()).select_from(NormalizedPost).where(
                NormalizedPost.source_type == SourceType.OWNED
            )
        )
        norm_comp = s.scalar(
            select(func.count()).select_from(NormalizedPost).where(
                NormalizedPost.source_type == SourceType.COMPETITOR
            )
        )
        table = Table(title="Normalization coverage")
        table.add_column("Source")
        table.add_column("Raw", justify="right")
        table.add_column("Normalized", justify="right")
        table.add_row("owned", str(owned_total), str(norm_owned))
        table.add_row("competitor", str(comp_total), str(norm_comp))
        console.print(table)

        et = Table(title="Extracted entities")
        et.add_column("Entity")
        et.add_column("Count", justify="right")
        et.add_row("prices", str(s.scalar(select(func.count()).select_from(ExtractedPrice))))
        et.add_row("coupons", str(s.scalar(select(func.count()).select_from(ExtractedCoupon))))
        et.add_row("links", str(s.scalar(select(func.count()).select_from(ExtractedLink))))
        merch = s.scalar(
            select(func.count()).select_from(ExtractedLink).where(
                ExtractedLink.merchant_key.isnot(None)
            )
        )
        et.add_row("links w/ known merchant", str(merch))
        console.print(et)

        # merchant distribution (deterministic, from known link domains)
        dist = s.execute(
            select(NormalizedPost.primary_merchant_key, func.count())
            .where(NormalizedPost.primary_merchant_key.isnot(None))
            .group_by(NormalizedPost.primary_merchant_key)
            .order_by(func.count().desc())
        ).all()
        if dist:
            mt = Table(title="Primary merchant (detected, known domains only)")
            mt.add_column("merchant")
            mt.add_column("posts", justify="right")
            for k, c in dist:
                mt.add_row(k, str(c))
            console.print(mt)


@app.command("classify")
def classify(
    k: int = typer.Option(6, help="Number of post-type clusters to learn"),
    seed: int = typer.Option(42, help="Fixed seed for deterministic clustering"),
) -> None:
    """Phase 3: learn post-type clusters from normalized data (no hardcoding)."""
    from src.services.classification.classifier import PostClassifier

    job = JobRunner().run_collector(
        PostClassifier(k=k, seed=seed),
        collection_type=CollectionType.MANUAL,
        target=f"classify(k={k})",
    )
    _print_job(job)


@app.command("classify-status")
def classify_status() -> None:
    """Show the learned post-type clusters, their descriptors, and sizes."""
    from sqlalchemy import func, select

    from src.db.models_classification import (
        CLASSIFICATION_VERSION,
        PostClassification,
        PostTypeCluster,
    )

    with session_scope() as s:
        clusters = s.scalars(
            select(PostTypeCluster)
            .where(PostTypeCluster.classification_version == CLASSIFICATION_VERSION)
            .order_by(PostTypeCluster.size.desc())
        ).all()
        if not clusters:
            console.print("[yellow]No clusters yet. Run `tgagent classify`.[/yellow]")
            return
        total = sum(c.size for c in clusters) or 1
        table = Table(title=f"Learned post-type clusters (v{CLASSIFICATION_VERSION})")
        table.add_column("idx")
        table.add_column("descriptor (data-derived)")
        table.add_column("posts", justify="right")
        table.add_column("share", justify="right")
        table.add_column("avg conf", justify="right")
        for c in clusters:
            avg_conf = s.scalar(
                select(func.avg(PostClassification.confidence)).where(
                    PostClassification.cluster_id == c.id
                )
            )
            table.add_row(
                str(c.cluster_index),
                c.descriptor or "-",
                str(c.size),
                f"{100 * c.size / total:.1f}%",
                f"{(avg_conf or 0):.2f}",
            )
        console.print(table)


@app.command("merchant-intel")
def merchant_intel() -> None:
    """Phase 4: build merchant profiles, scores, windows, and opportunities."""
    from src.services.intelligence.merchant import MerchantIntelligenceEngine

    job = JobRunner().run_collector(
        MerchantIntelligenceEngine(),
        collection_type=CollectionType.MANUAL,
        target="merchant_intel",
    )
    _print_job(job)


@app.command("merchant-intel-status")
def merchant_intel_status() -> None:
    """Show merchant profiles (engagement, pricing, activity) + opportunities."""
    from sqlalchemy import select

    from src.db.models_intelligence import (
        MERCHANT_INTEL_VERSION,
        MerchantOpportunity,
        MerchantProfile,
    )

    with session_scope() as s:
        profiles = s.scalars(
            select(MerchantProfile)
            .where(MerchantProfile.intel_version == MERCHANT_INTEL_VERSION)
            .order_by(MerchantProfile.post_count_owned.desc())
        ).all()
        if not profiles:
            console.print("[yellow]No merchant profiles. Run `tgagent merchant-intel`.[/yellow]")
            return
        t = Table(title="Merchant profiles")
        for col in ("merchant", "posts", "avg views/day", "avg fwd", "price med", "consistency", "conf"):
            t.add_column(col)
        for p in profiles:
            t.add_row(
                p.merchant_key,
                str(p.post_count_owned),
                f"{p.avg_views_per_day:.1f}" if p.avg_views_per_day is not None else "-",
                f"{p.avg_forwards:.1f}" if p.avg_forwards is not None else "-",
                f"{p.price_median:.0f}" if p.price_median is not None else "-",
                f"{p.consistency_score:.2f}" if p.consistency_score is not None else "-",
                f"{p.confidence:.2f}",
            )
        console.print(t)
        console.print(
            "[dim]Marked UNAVAILABLE (never estimated): conversion/CTR (no API), "
            "discount % (needs MRP+current pairing), business category (not extracted yet).[/dim]"
        )

        opps = s.scalars(
            select(MerchantOpportunity)
            .where(MerchantOpportunity.intel_version == MERCHANT_INTEL_VERSION)
            .order_by(MerchantOpportunity.confidence.desc())
        ).all()
        if opps:
            ot = Table(title="Merchant opportunities (evidence-backed)")
            for col in ("merchant", "kind", "confidence", "description"):
                ot.add_column(col)
            for o in opps:
                ot.add_row(o.merchant_key, o.kind, f"{o.confidence:.2f}", o.description[:70])
            console.print(ot)
        else:
            console.print("[dim]No opportunities detected with current evidence.[/dim]")


@app.command("competitor-intel")
def competitor_intel() -> None:
    """Phase 5: build competitor profiles and benchmarks."""
    from src.services.intelligence.competitor import CompetitorIntelligenceEngine

    job = JobRunner().run_collector(
        CompetitorIntelligenceEngine(),
        collection_type=CollectionType.MANUAL,
        target="competitor_intel",
    )
    _print_job(job)


@app.command("competitor-intel-status")
def competitor_intel_status() -> None:
    """Show competitor profiles and similarity to us."""
    from src.services.intelligence.competitor import latest_profiles

    with session_scope() as s:
        profiles = sorted(latest_profiles(s), key=lambda p: -(p.post_count or 0))
        if not profiles:
            console.print("[yellow]No competitor profiles. Run `tgagent competitor-intel`.[/yellow]")
            return
        t = Table(title="Competitor profiles (vs our channel)")
        for col in ("competitor", "posts", "posts/day", "cta", "coupon", "multi", "media", "similarity", "conf"):
            t.add_column(col)
        for p in profiles:
            def f(v, pct=False):
                if v is None:
                    return "-"
                return f"{v*100:.0f}%" if pct else f"{v:.2f}"
            t.add_row(
                p.username, str(p.post_count),
                f(p.posts_per_day), f(p.cta_rate, True), f(p.coupon_rate, True),
                f(p.multi_deal_rate, True), f(p.media_rate, True),
                f(p.similarity_to_owned), f(p.confidence),
            )
        console.print(t)
        console.print(
            "[dim]t.me/s snapshot: views are rounded/cumulative; forwards & reactions "
            "unavailable; business category not extracted. Small samples -> low confidence.[/dim]"
        )


@app.command("learn")
def learn() -> None:
    """Phase 6: learn channel style, post-type performance, and insights."""
    from src.services.learning.channel_learning import ChannelLearningEngine

    job = JobRunner().run_collector(
        ChannelLearningEngine(), collection_type=CollectionType.MANUAL, target="channel_learning"
    )
    _print_job(job)


@app.command("learn-status")
def learn_status() -> None:
    """Show learned channel knowledge: style, post-type ranking, insights."""
    from sqlalchemy import select

    from src.db.models_learning import (
        LEARNING_VERSION,
        ChannelStyleProfile,
        LearningRecord,
        PostTypePerformance,
    )

    with session_scope() as s:
        style = s.scalar(
            select(ChannelStyleProfile).where(
                ChannelStyleProfile.learning_version == LEARNING_VERSION
            )
        )
        if style is None:
            console.print("[yellow]No learning yet. Run `tgagent learn`.[/yellow]")
            return
        console.print(
            f"[bold]Channel style[/bold] (n={style.post_count}, conf {style.confidence:.2f}): "
            f"avg caption {style.avg_caption_len:.0f} chars, {style.avg_emojis:.1f} emojis/post, "
            f"CTA {style.cta_rate*100:.0f}%, coupon {style.coupon_rate*100:.0f}%, "
            f"multi-deal {style.multi_deal_rate*100:.0f}%, media {style.media_rate*100:.0f}%, "
            f"~{style.posts_per_day:.1f} posts/day"
        )
        if style.top_emojis:
            console.print("  top emojis: " + " ".join(f"{e}×{c}" for e, c in style.top_emojis[:6]))
        if style.top_hours_ist:
            console.print("  top hours (IST): " + ", ".join(f"{h:02d}:00" for h, _ in style.top_hours_ist))

        perf = s.scalars(
            select(PostTypePerformance)
            .where(PostTypePerformance.learning_version == LEARNING_VERSION)
            .order_by(PostTypePerformance.rank_by_views_per_day)
        ).all()
        pt = Table(title="Post-type performance (views/day)")
        for col in ("rank", "post type", "posts", "share", "avg views/day", "avg fwd", "conf"):
            pt.add_column(col)
        for p in perf:
            pt.add_row(
                str(p.rank_by_views_per_day), (p.post_type or "-")[:34], str(p.post_count),
                f"{(p.share or 0)*100:.0f}%",
                f"{p.avg_views_per_day:.1f}" if p.avg_views_per_day is not None else "-",
                f"{p.avg_forwards:.1f}" if p.avg_forwards is not None else "-",
                f"{p.confidence:.2f}",
            )
        console.print(pt)

        recs = s.scalars(
            select(LearningRecord)
            .where(LearningRecord.learning_version == LEARNING_VERSION)
            .order_by(LearningRecord.confidence.desc())
        ).all()
        rt = Table(title="Learnings (evidence-backed)")
        for col in ("category", "confidence", "statement"):
            rt.add_column(col)
        for r in recs:
            rt.add_row(r.category, f"{r.confidence:.2f}", r.statement[:80])
        console.print(rt)


@app.command("growth")
def growth() -> None:
    """Phase 7: generate the growth strategy + ranked recommendations."""
    from src.services.intelligence.growth import GrowthEngine

    job = JobRunner().run_collector(
        GrowthEngine(), collection_type=CollectionType.MANUAL, target="growth"
    )
    _print_job(job)


@app.command("growth-status")
def growth_status() -> None:
    """Show the growth strategy blueprint and ranked recommendations."""
    from sqlalchemy import select

    from src.db.models_growth import (
        GROWTH_VERSION,
        GrowthRecommendation,
        GrowthStrategy,
    )

    with session_scope() as s:
        strat = s.scalar(
            select(GrowthStrategy).where(GrowthStrategy.growth_version == GROWTH_VERSION)
        )
        if strat is None:
            console.print("[yellow]No strategy yet. Run `tgagent growth`.[/yellow]")
            return
        console.print(
            f"[bold]Growth strategy[/bold] — mode=[cyan]{strat.mode}[/cyan], "
            f"channel type=[cyan]{strat.channel_type}[/cyan], confidence {strat.confidence:.2f}"
        )
        bp = strat.blueprint or {}
        if bp.get("posting_frequency_baseline") is not None:
            console.print(f"  posting baseline: ~{bp['posting_frequency_baseline']} posts/day")
        if bp.get("recommended_hours_ist"):
            console.print(f"  recommended hours (IST): {bp['recommended_hours_ist']}")
        if bp.get("emoji_strategy"):
            console.print(f"  emoji strategy: {' '.join(bp['emoji_strategy'])}")
        plan = bp.get("posting_plan") or []
        if plan:
            pt = Table(title=f"Suggested posting schedule (~{bp.get('posting_frequency_baseline'):.0f}/day, IST)")
            for col in ("day-part", "hours", "current/day", "suggested/day", "avg views/day", "action"):
                pt.add_column(col)
            for p in plan:
                pt.add_row(p["part"], p["hours"], str(p["current_posts_per_day"]),
                           str(p["recommended_posts_per_day"]), str(p["avg_views_per_day"]), p["action"])
            console.print(pt)

        mix = bp.get("content_mix") or []
        if mix:
            mt = Table(title="Recommended content mix")
            for col in ("post type", "current share", "views/day", "action"):
                mt.add_column(col)
            for m in mix:
                mt.add_row((m["post_type"] or "-")[:34], f"{(m['current_share'] or 0)*100:.0f}%",
                           f"{m['avg_views_per_day']:.1f}" if m.get("avg_views_per_day") else "-",
                           m["action"])
            console.print(mt)

        recs = s.scalars(
            select(GrowthRecommendation)
            .where(GrowthRecommendation.growth_version == GROWTH_VERSION)
            .order_by(GrowthRecommendation.priority)
        ).all()
        rt = Table(title="Growth recommendations (ranked)")
        for col in ("#", "category", "conf", "recommendation"):
            rt.add_column(col)
        for r in recs:
            rt.add_row(str(r.priority), r.category, f"{r.confidence:.2f}", r.recommendation[:74])
        console.print(rt)
        console.print("[dim]Every recommendation stores its reasoning + evidence; "
                      "the Growth Engine plans strategy — it never writes posts.[/dim]")


@app.command("reason")
def reason(window: int = typer.Option(30, help="Comparison window in days")) -> None:
    """Phase 8: detect performance shifts and explain WHY (data-backed)."""
    from src.services.intelligence.reasoning import ReasoningEngine

    job = JobRunner().run_collector(
        ReasoningEngine(window_days=window), collection_type=CollectionType.MANUAL, target="reasoning"
    )
    _print_job(job)


@app.command("reason-status")
def reason_status() -> None:
    """Show reasoned insights: what shifted, why, evidence, confidence."""
    from sqlalchemy import select

    from src.db.models_reasoning import REASONING_VERSION, ReasonedInsight

    with session_scope() as s:
        insights = s.scalars(
            select(ReasonedInsight)
            .where(ReasonedInsight.reasoning_version == REASONING_VERSION)
            .order_by(ReasonedInsight.confidence.desc())
        ).all()
        if not insights:
            console.print("[yellow]No notable changes in the last month (or run `tgagent reason`).[/yellow]")
            return
        friendly = {
            "posting_volume": "How often you post",
            "post_type_mix": "What you post",
            "content_style": "Your post style",
            "engagement": "Views per post",
        }
        confidence_word = lambda c: "high" if c >= 0.66 else "medium" if c >= 0.33 else "early signal"
        console.print("[bold]What changed in the last month, and why:[/bold]\n")
        for ins in insights:
            arrow = "📈" if ins.direction == "up" else "📉" if ins.direction == "down" else "•"
            label = friendly.get(ins.metric, ins.metric)
            console.print(f"{arrow} [bold]{label}[/bold]  [dim](confidence: {confidence_word(ins.confidence)})[/dim]")
            console.print(f"   {ins.observation}")
            console.print(f"   [green]→ {ins.reasoning}[/green]\n")


@app.command("enrich-deals")
def enrich_deals(json_path: str = typer.Argument(..., help="Path to raw deals JSON")) -> None:
    """Phase 9: enrich raw deals into validated structured deals (source_truth/06)."""
    import json

    from src.services.generation.enrichment import DealEnrichmentEngine, RawDeal

    raw = [RawDeal.from_dict(d) for d in json.loads(open(json_path, encoding="utf-8").read())]
    with session_scope() as s:
        enriched = DealEnrichmentEngine(s).enrich_batch(raw)
        rows = [(d.title, d.merchant_key, d.current_price, d.original_price,
                 d.discount_percent, d.is_loot_deal, d.deal_validity, d.price_confidence_score)
                for d in enriched]
    t = Table(title="Enriched deals")
    for col in ("title", "merchant", "price", "mrp", "disc%", "loot", "validity", "confidence"):
        t.add_column(col)
    for title, mk, cur, mrp, disc, loot, val, conf in rows:
        t.add_row((title or "")[:28], mk or "unknown",
                  f"{cur:.0f}" if cur is not None else "-",
                  f"{mrp:.0f}" if mrp is not None else "-",
                  f"{disc:.0f}" if disc is not None else "-",
                  "yes" if loot else "no" if loot is False else "?",
                  val, f"{conf:.2f}")
    console.print(t)
    console.print("[dim]BLOCKED merchants (e.g. AJIO) are detected but their prices cannot be "
                  "verified; affiliate links pending GrabOn shortener integration.[/dim]")


@app.command("generate")
def generate(
    json_path: str = typer.Argument(..., help="Path to raw deals JSON"),
    count: int = typer.Option(5, help="How many deals to select"),
    collection: bool = typer.Option(True, help="Also produce a collection post"),
) -> None:
    """Phase 9: enrich -> rank -> select -> format into draft posts (never auto-publishes)."""
    import json

    from src.services.generation.engine import PostGenerationEngine

    raw = json.loads(open(json_path, encoding="utf-8").read())
    job = JobRunner().run_collector(
        PostGenerationEngine(raw, count=count, make_collection=collection),
        collection_type=CollectionType.MANUAL, target="post_generation",
    )
    _print_job(job)


@app.command("fetch-deals")
def fetch_deals(limit: int = typer.Option(20, help="How many latest deals to fetch")) -> None:
    """Fetch TODAY's latest deals from the deal source and enrich them (verify the
    connection + field mapping before generating posts)."""
    from src.services.generation.deal_source import DealSourceClient
    from src.services.generation.enrichment import DealEnrichmentEngine

    client = DealSourceClient()
    ok, reason = client.available()
    if not ok:
        console.print(f"[yellow]Deal source unavailable:[/yellow] {reason}")
        raise typer.Exit(code=1)
    raw = client.fetch_latest(limit=limit)
    if not raw:
        console.print("[yellow]No deals returned. Check DEAL_API_BASE, auth, and response schema.[/yellow]")
        return
    with session_scope() as s:
        enriched = DealEnrichmentEngine(s).enrich_batch(raw)
        rows = [(d.title, d.merchant_key, d.current_price, d.discount_percent, d.deal_validity) for d in enriched]
    t = Table(title=f"Latest deals fetched + enriched ({len(rows)})")
    for col in ("title", "merchant", "price", "disc%", "validity"):
        t.add_column(col)
    for title, mk, cur, disc, val in rows:
        t.add_row((title or "")[:34], mk or "unknown",
                  f"{cur:.0f}" if cur is not None else "-",
                  f"{disc:.0f}" if disc is not None else "-", val)
    console.print(t)


@app.command("generate-live")
def generate_live(
    limit: int = typer.Option(20, help="Latest deals to fetch"),
    count: int = typer.Option(5, help="How many to select for posts"),
    collection: bool = typer.Option(True, help="Also produce a collection post"),
) -> None:
    """Fetch TODAY's latest deals from the source, then enrich -> rank -> select ->
    format into draft posts. This is the real path for new posts (never auto-publishes)."""
    from src.services.generation.deal_source import DealSourceClient
    from src.services.generation.engine import LiveDealGenerationEngine

    client = DealSourceClient()
    ok, reason = client.available()
    if not ok:
        console.print(f"[yellow]Deal source unavailable:[/yellow] {reason}")
        raise typer.Exit(code=1)
    raw = [rd.__dict__ for rd in client.fetch_latest(limit=limit)]
    job = JobRunner().run_collector(
        LiveDealGenerationEngine(raw, count=count),
        collection_type=CollectionType.MANUAL, target="generate_live",
    )
    _print_job(job)


@app.command("regenerate-drafts")
def regenerate_drafts(
    limit: int = typer.Option(20, help="Latest deals to fetch"),
    count: int = typer.Option(6, help="How many drafts to produce"),
) -> None:
    """Clear old DRAFT posts and regenerate from today's live deals — so drafts pick up
    the current strategy (emoji policy, content mix) and real grbn.in affiliate links."""
    from src.db.models_generation import GeneratedPost, PostStatus
    from src.services.generation.deal_source import DealSourceClient
    from src.services.generation.engine import LiveDealGenerationEngine

    client = DealSourceClient()
    ok, reason = client.available()
    if not ok:
        console.print(f"[yellow]Deal source unavailable:[/yellow] {reason}")
        raise typer.Exit(code=1)
    with session_scope() as s:
        removed = s.query(GeneratedPost).filter(GeneratedPost.status == PostStatus.DRAFT).delete()
    console.print(f"Cleared {removed} old draft(s). Fetching fresh deals…")
    raw = [rd.__dict__ for rd in client.fetch_latest(limit=limit)]
    job = JobRunner().run_collector(
        LiveDealGenerationEngine(raw, count=count),
        collection_type=CollectionType.MANUAL, target="regenerate_drafts",
    )
    _print_job(job)


@app.command("generate-from-observed")
def generate_from_observed(
    count: int = typer.Option(5, help="How many posts to draft"),
    limit: int = typer.Option(30, help="How many recent posts to scan for candidates"),
    window: int = typer.Option(120, help="Look-back window in days"),
) -> None:
    """Phase 9: draft posts from REAL observed deals (real, reachable links).

    Loot/multi-link deals are rendered as themed collections like the channel
    actually posts them. No fabricated URLs — links come straight from history.
    """
    from src.services.generation.engine import ObservedPostGenerationEngine

    job = JobRunner().run_collector(
        ObservedPostGenerationEngine(limit=limit, count=count, window_days=window),
        collection_type=CollectionType.MANUAL, target="post_generation_observed",
    )
    _print_job(job)


@app.command("generated-status")
def generated_status() -> None:
    """Show generated draft posts (rendered text, bucket, score, status)."""
    from sqlalchemy import select

    from src.db.models_generation import GeneratedPost

    with session_scope() as s:
        posts = s.scalars(select(GeneratedPost).order_by(GeneratedPost.id.desc()).limit(12)).all()
        if not posts:
            console.print("[yellow]No generated posts. Run `tgagent generate <deals.json>`.[/yellow]")
            return
        for p in posts:
            console.print(
                f"[bold]#{p.id}[/bold] [{p.post_type}/{p.selection_bucket}] "
                f"score={p.rank_score:.1f} status=[cyan]{p.status}[/cyan]"
            )
            for line in (p.rendered_text or "").splitlines():
                console.print(f"    {line}")
            console.print("")


@app.command("publish")
def publish(
    post_id: int = typer.Argument(..., help="Generated post id"),
    channel: str = typer.Argument(..., help="Target channel @username"),
    confirm: bool = typer.Option(False, "--confirm", help="Actually attempt to publish"),
) -> None:
    """Phase 9: attempt to publish a draft (gated: needs admin rights + --confirm)."""
    from src.services.generation.publishing import Publisher

    res = Publisher().publish(post_id, channel, confirm=confirm)
    color = "green" if res["ok"] else "yellow"
    console.print(f"[{color}]{res['status']}[/{color}]: {res['note']}")


@app.command("seed-events")
def seed_events() -> None:
    """Seed the India sale-event calendar (exact national dates; approximate merchant sales)."""
    from datetime import datetime, timezone

    from src.services.planning.calendar import seed_sale_events

    with session_scope() as s:
        n = seed_sale_events(s, datetime.now(timezone.utc).date())
    console.print(f"[green]Sale calendar seeded[/green] ({n} new events).")


@app.command("events-upcoming")
def events_upcoming(within: int = typer.Option(400, help="Look-ahead window in days")) -> None:
    """List upcoming sale events with days-away and date confidence."""
    from datetime import datetime, timezone

    from src.services.planning.calendar import upcoming_events

    today = datetime.now(timezone.utc).date()
    with session_scope() as s:
        events = upcoming_events(s, today, within_days=within)
        rows = [(e.name, e.next_date.isoformat(), (e.next_date - today).days,
                 e.date_confidence, e.merchant_key or "multi") for e in events]
    if not rows:
        console.print("[yellow]No events. Run `tgagent seed-events`.[/yellow]")
        return
    t = Table(title="Upcoming sale events")
    for col in ("event", "date", "days away", "confidence", "merchant"):
        t.add_column(col)
    for name, d, days, conf, m in rows:
        t.add_row(name, d, str(days), conf, m)
    console.print(t)
    console.print("[dim]Approximate = month-level; merchant sale dates are announced near the "
                  "event and must be confirmed. Flash sales are not predictable.[/dim]")


@app.command("plan")
def plan(event_lead: int = typer.Option(30, help="Include event campaign if within N days")) -> None:
    """Phase 10: generate daily + weekly + upcoming-event campaign plans."""
    from src.services.planning.campaign import CampaignPlanningEngine

    job = JobRunner().run_collector(
        CampaignPlanningEngine(event_lead_days=event_lead),
        collection_type=CollectionType.MANUAL, target="campaign_planning",
    )
    _print_job(job)


@app.command("plan-status")
def plan_status() -> None:
    """Show the generated daily / weekly / event plans."""
    import json
    from sqlalchemy import select

    from src.db.models_campaign import CAMPAIGN_VERSION, CampaignPlan

    with session_scope() as s:
        plans = s.scalars(
            select(CampaignPlan).where(CampaignPlan.campaign_version == CAMPAIGN_VERSION)
            .order_by(CampaignPlan.plan_type)
        ).all()
        if not plans:
            console.print("[yellow]No plans. Run `tgagent plan`.[/yellow]")
            return
        for p in plans:
            console.print(f"\n[bold]{p.title}[/bold] (confidence {p.confidence:.2f})")
            bp = p.blueprint or {}
            if p.plan_type == "daily":
                console.print(f"  Posts today: {bp.get('posts_planned')}")
                for a in bp.get("deal_type_allocation", []):
                    vpd = a.get("avg_views_per_day")
                    console.print(f"   • {a['target_posts']}× {a['deal_type']}"
                                  + (f"  (~{vpd:.0f} views/day)" if vpd else ""))
                if bp.get("posting_windows"):
                    console.print("  Windows (IST): " + ", ".join(
                        f"{w['part']} {w['hours']}→{w['posts']}" for w in bp["posting_windows"]))
                if bp.get("merchant_allocation"):
                    console.print("  Merchant mix (recent): " + ", ".join(
                        f"{m['merchant']} {m['recent_share']*100:.0f}%" for m in bp["merchant_allocation"][:4]))
                eo = p.expected_outcome or {}
                if eo.get("estimated_daily_views"):
                    console.print(f"  Expected reach: ~{eo['estimated_daily_views']:,} views (estimate)")
            elif p.plan_type == "weekly":
                for d in bp.get("daily_themes", []):
                    console.print(f"   {d['day']} {d['date']}: {d['theme_focus']} ({d['posts_planned']} posts)")
                if bp.get("upcoming_events"):
                    console.print("  Events: " + ", ".join(
                        f"{e['name']} ({e['days_away']}d, {e['date_confidence']})" for e in bp["upcoming_events"]))
            elif p.plan_type == "event":
                console.print(f"  {bp.get('event')} in ~{bp.get('days_away')}d "
                              f"({bp.get('date_confidence')}); ramp to "
                              f"{bp.get('recommended_posts_per_day_during_event')} posts/day "
                              f"(from {bp.get('baseline_posts_per_day')}), focus: {bp.get('merchant_focus')}")
                for step in bp.get("prep_checklist", []):
                    console.print(f"   ☐ {step}")
            for r in (p.risks or []):
                console.print(f"  [yellow]⚠ {r['kind']}:[/yellow] {r['detail']}")


@app.command("brief")
def brief(weekly: bool = typer.Option(False, help="Weekly summary instead of daily")) -> None:
    """Show the current plan digest — the AI plan's narrative doubles as the operator
    briefing (win/concern/do-today). Reads the cached plan, does not regenerate."""
    from src.controllers import service

    data = service.weekly_report() if weekly else service.digest()
    text = (data.get("ai_summary") if weekly else data.get("digest")) or ""
    if not text:
        console.print("[yellow]No plan digest yet — run the daily/weekly planner first.[/yellow]")
        raise typer.Exit(code=1)
    console.print(text)


@app.command("write-post")
def write_post(deal_id: str = typer.Argument(..., help="Enriched deal_id to write copy for")) -> None:
    """AI-write a Telegram post for an enriched deal (grounded in its real facts)."""
    from src.ai.client import AIUnavailable
    from src.ai.copywriter import Copywriter

    try:
        console.print(Copywriter().write_for_deal(deal_id))
    except AIUnavailable as e:
        console.print(f"[yellow]{e}[/yellow]")
        raise typer.Exit(code=1)


@app.command("dev-chats")
def dev_chats_cmd(limit: int = typer.Option(30, help="How many recent chats to list")) -> None:
    """DEV ONLY: list your recent Telegram chats (name, kind, chat_ref) so you can pick
    the exact --chat value to pass to `dev-send`. Includes personal DMs, groups, and
    channels your logged-in account can already see."""
    from src.services.generation.dev_send import list_chats

    try:
        rows = list_chats(limit)
    except Exception as e:  # noqa: BLE001 — surface any Telethon/config error directly to the operator
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    table = Table("name", "kind", "chat_ref", "id")
    for r in rows:
        table.add_row(r["name"], r["kind"], r["chat_ref"], str(r["id"]))
    console.print(table)


@app.command("dev-send")
def dev_send_cmd(
    chat: str = typer.Argument(..., help="Target chat your logged-in account can already see: "
                                          "@username, invite-linked group, or numeric chat ID"),
    text: str = typer.Option(None, "--text", help="Raw message text to send"),
    deal_id: str = typer.Option(None, "--deal-id",
                                help="AI-write the message from this enriched deal_id instead of --text"),
) -> None:
    """DEV ONLY: send a real message to a chat of your choosing via your own logged-in
    Telegram session. Bypasses the production publish() gate entirely (no admin-rights
    check, no sign-off) — for manually testing the send mechanic against a personal
    test chat. Never point this at the production owned channel."""
    from src.ai.client import AIUnavailable
    from src.services.generation.dev_send import dev_send

    if not text and not deal_id:
        console.print("[red]Provide --text or --deal-id[/red]")
        raise typer.Exit(code=1)
    if deal_id:
        from src.ai.copywriter import Copywriter
        try:
            text = Copywriter().write_for_deal(deal_id)
        except AIUnavailable as e:
            console.print(f"[yellow]{e}[/yellow]")
            raise typer.Exit(code=1)
    try:
        result = dev_send(chat, text)
    except Exception as e:  # noqa: BLE001 — surface any Telethon/config error directly to the operator
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]{result}[/green]")


@app.command("dev-publish-drafts")
def dev_publish_drafts_cmd(
    chat: str = typer.Argument(..., help="Target chat, same as `dev-send` (use `--` before a "
                                          "numeric/negative chat ID, e.g. -- -5291594307)"),
    day: str = typer.Option(..., "--day", help="AI-plan day to pull existing drafts from, "
                                               "e.g. 2026-07-13 (must match a plan's target_date)"),
    include_sent: bool = typer.Option(False, "--include-sent",
                                      help="Also re-send drafts already dev-sent earlier (off by default)"),
    pace_seconds: float = typer.Option(1.5, help="Delay between sends"),
) -> None:
    """DEV ONLY: push ALREADY-GENERATED jit_fill drafts for --day straight to `chat`,
    without re-running any fetching/planning/AI-copy step. Use this when drafts
    already exist in generated_posts (e.g. from an earlier collect_data.py run or
    manual fill_due_slots call) and you just want them delivered now."""
    from datetime import date as date_cls

    from src.services.generation.dev_send import drafts_for_day, publish_drafts

    try:
        day_obj = date_cls.fromisoformat(day)
    except ValueError:
        console.print(f"[red]Invalid --day {day!r}, expected YYYY-MM-DD[/red]")
        raise typer.Exit(code=1)
    ids = drafts_for_day(day_obj, include_already_sent=include_sent)
    if not ids:
        console.print(f"[yellow]No pending drafts found for {day}.[/yellow]")
        raise typer.Exit(code=0)
    console.print(f"Sending {len(ids)} draft(s) for {day} to {chat!r}...")
    try:
        results = publish_drafts(ids, chat, pace_seconds=pace_seconds)
    except Exception as e:  # noqa: BLE001 — surface any Telethon/config error directly to the operator
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    ok = sum(1 for r in results if r["ok"])
    for r in results:
        if not r["ok"]:
            console.print(f"[red]  draft #{r['draft_id']} failed: {r['note']}[/red]")
    console.print(f"[green]Sent {ok}/{len(results)}[/green]")


@app.command("coach")
def coach(question: str = typer.Argument(..., help="Your growth question")) -> None:
    """Ask the agentic growth coach — it queries the engines and answers, grounded."""
    from src.ai.client import AIUnavailable
    from src.ai.coach import GrowthCoach
    from src.config.settings import get_settings
    from src.services.ai_outputs import record_ai_output

    try:
        answer = GrowthCoach().ask(question)
        console.print(answer)
        record_ai_output("coach_qa", f"Q: {question}\nA: {answer}", get_settings().ai_model)
    except AIUnavailable as e:
        console.print(f"[yellow]{e}[/yellow]")
        raise typer.Exit(code=1)


@app.command("pipeline")
def pipeline(
    collect: bool = typer.Option(False, help="Also run competitor collection first (network)"),
    brief_after: bool = typer.Option(True, help="Generate an AI briefing at the end (needs API key)"),
) -> None:
    """Run the whole intelligence stack end-to-end: normalize → classify → merchant/
    competitor intel → learn → growth → reason → plan (→ AI brief)."""
    from src.services.classification.classifier import PostClassifier
    from src.services.intelligence.competitor import CompetitorIntelligenceEngine
    from src.services.intelligence.growth import GrowthEngine
    from src.services.intelligence.merchant import MerchantIntelligenceEngine
    from src.services.intelligence.reasoning import ReasoningEngine
    from src.services.learning.channel_learning import ChannelLearningEngine
    from src.services.planning.campaign import CampaignPlanningEngine
    from src.services.processing.normalizer import PostNormalizer

    runner = JobRunner()
    steps = [
        ("normalize", PostNormalizer()),
        ("classify", PostClassifier(k=6)),
        ("merchant-intel", MerchantIntelligenceEngine()),
        ("competitor-intel", CompetitorIntelligenceEngine()),
        ("learn", ChannelLearningEngine()),
        ("growth", GrowthEngine()),
        ("reason", ReasoningEngine()),
        ("plan", CampaignPlanningEngine()),
    ]
    if collect:
        from src.services.collection.telegram_competitor import CompetitorCollector
        for u in get_settings().competitor_channels:
            runner.run_collector(CompetitorCollector(u), collection_type=CollectionType.INCREMENTAL, target=u)

    for name, engine in steps:
        job = runner.run_collector(engine, collection_type=CollectionType.MANUAL, target=name)
        mark = "✓" if job.status == "completed" else "•"
        console.print(f"  {mark} {name}: {job.status} (added={job.records_added})"
                      + (f" — {job.error_message}" if job.error_message else ""))
    console.print("[green]Pipeline complete.[/green]")
    if brief_after:
        from src.controllers.service import digest as _digest
        d = _digest().get("digest")
        if d:
            console.print("\n[bold]Plan digest:[/bold]\n" + d)


@app.command("status")
def status() -> None:
    """Show stored-data counts and the most recent collection jobs."""
    with session_scope() as s:
        counts = {
            "channels": s.scalar(select(func.count()).select_from(Channel)),
            "posts": s.scalar(select(func.count()).select_from(Post)),
            "competitors": s.scalar(select(func.count()).select_from(Competitor)),
            "competitor_posts": s.scalar(select(func.count()).select_from(CompetitorPost)),
            "merchants": s.scalar(select(func.count()).select_from(Merchant)),
            "merchant_products": s.scalar(select(func.count()).select_from(MerchantProduct)),
        }
        blocked = s.scalars(
            select(Merchant).where(Merchant.access_status == SourceAccessStatus.BLOCKED)
        ).all()
        recent = s.scalars(
            select(CollectionJob).order_by(CollectionJob.id.desc()).limit(10)
        ).all()

        ct = Table(title="Stored data")
        ct.add_column("Entity")
        ct.add_column("Count", justify="right")
        for k, v in counts.items():
            ct.add_row(k, str(v))
        console.print(ct)

        if blocked:
            console.print(
                "[yellow]BLOCKED merchants (represented, never collected):[/yellow] "
                + ", ".join(m.display_name for m in blocked)
            )

        jt = Table(title="Recent jobs")
        for col in ("id", "type", "target", "status", "proc", "add", "upd", "ms"):
            jt.add_column(col)
        for j in recent:
            jt.add_row(
                str(j.id), j.job_type, (j.target or "")[:28], j.status,
                str(j.records_processed), str(j.records_added),
                str(j.records_updated), str(j.duration_ms or ""),
            )
        console.print(jt)


@app.command("dashboard")
def dashboard(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8765, help="Port"),
) -> None:
    """Phase 12: launch the local dashboard (FastAPI — actionable insights, analytics,
    a JSON API at /api/*, and OpenAPI docs at /api/docs)."""
    from src.main import serve

    url = f"http://{host}:{port}"
    console.print(f"[green]Dashboard running at[/green] {url}  "
                  f"[dim]· API docs {url}/api/docs · Ctrl-C to stop[/dim]")
    serve(host=host, port=port)


@app.command("affiliate-link")
def affiliate_link(
    url: str = typer.Argument(..., help="Product URL to convert"),
    merchant: str = typer.Option(None, "--merchant", help="Known merchant key (else auto-detect)"),
) -> None:
    """Generate an affiliate (+ short) link via the configured provider."""
    from src.services.affiliate import get_affiliate_provider

    provider = get_affiliate_provider()
    res = provider.generate(url, merchant)
    console.print(f"[bold]provider[/bold]: {res.provider}   [bold]merchant[/bold]: {res.merchant_key or 'unknown'}")
    console.print(f"[bold]affiliate[/bold]: {res.affiliate_url or '(no rule — clean URL)'}")
    console.print(f"[bold]short[/bold]: {res.short_url or '(not shortened)'}")
    console.print(f"[green bold]FINAL (used in post)[/green bold]: {res.final_url}")
    for n in res.notes:
        console.print(f"[dim]• {n}[/dim]")


@app.command("run-scheduler")
def run_scheduler(
    key: str = typer.Argument(None, help="Job key (omit to list all jobs)"),
) -> None:
    """Run one scheduler job once (for OS cron / manual triggers). Omit key to list jobs."""
    from src.controllers.schedulers import REGISTRY
    if not key:
        for j in REGISTRY.status()["jobs"]:
            console.print(f"  {j['key']:22} {j['cadence']:16} [{j['priority']}] {j['name']}")
        return
    REGISTRY.run(key)
    logs = REGISTRY.recent_logs(limit=1)
    if logs:
        r = logs[0]
        console.print(f"[green]{r['key']}[/green]: {r['status']} — {r.get('detail') or r.get('error') or ''}")


# --------------------------------------------------------------------------- #
# Phase 11 — Automation Engine
# --------------------------------------------------------------------------- #
@app.command("schedule-post")
def schedule_post(
    post_id: int = typer.Argument(..., help="Generated post id (a draft)"),
    channel: str = typer.Argument(..., help="Target channel @username"),
    at: str = typer.Option(None, "--at", help="When to send, IST, 'YYYY-MM-DD HH:MM'"),
    in_minutes: int = typer.Option(None, "--in", help="Send N minutes from now"),
) -> None:
    """Queue one draft for one channel at a specific time (idempotent)."""
    from datetime import datetime, timedelta, timezone

    from src.services.automation.queue import IST, enqueue

    if at:
        when = datetime.strptime(at, "%Y-%m-%d %H:%M").replace(tzinfo=IST).astimezone(timezone.utc)
    elif in_minutes is not None:
        when = datetime.now(timezone.utc) + timedelta(minutes=in_minutes)
    else:
        console.print("[red]Provide --at 'YYYY-MM-DD HH:MM' (IST) or --in <minutes>.[/red]")
        raise typer.Exit(1)

    with session_scope() as s:
        row, msg = enqueue(s, post_id, channel, when)
    color = "red" if row is None else "green"
    console.print(f"[{color}]{msg}[/{color}]")


@app.command("autoschedule")
def autoschedule_cmd(
    channel: str = typer.Argument(..., help="Target channel @username"),
    count: int = typer.Option(6, "--count", help="How many recent drafts to schedule"),
    day: str = typer.Option(None, "--day", help="Base day IST 'YYYY-MM-DD' (default today)"),
    post_ids: str = typer.Option(None, "--ids", help="Comma-separated draft ids (overrides --count)"),
) -> None:
    """Spread recent drafts across the daily plan's learned posting windows."""
    from datetime import date

    from src.services.automation.queue import autoschedule

    base_day = date.fromisoformat(day) if day else None
    ids = [int(x) for x in post_ids.split(",")] if post_ids else None
    with session_scope() as s:
        report = autoschedule(s, channel, count, base_day=base_day, post_ids=ids)

    if not report.get("ok"):
        console.print(f"[yellow]{report.get('reason')}[/yellow]")
        return
    t = Table(title=f"Auto-scheduled to {channel} (plan #{report['plan_id']}, {report['windows']} windows)")
    for col in ("queue id", "post id", "when (IST)"):
        t.add_column(col)
    for r in report["scheduled"]:
        t.add_row(str(r["scheduled_id"]), str(r["post_id"]), r["at_ist"])
    console.print(t)
    if report["skipped"]:
        console.print(f"[dim]{len(report['skipped'])} skipped: "
                      + "; ".join(f"#{x['post_id']} ({x['reason']})" for x in report["skipped"]) + "[/dim]")
    console.print("[dim]Queued only — nothing is sent until you run `tgagent automate` AND the "
                  "account has admin post rights on the channel.[/dim]")


@app.command("queue-status")
def queue_status(limit: int = typer.Option(30, help="Rows to show")) -> None:
    """Show the posting queue and per-status counts."""
    from src.db.models_automation import ScheduledPost

    with session_scope() as s:
        counts = dict(
            s.execute(
                select(ScheduledPost.status, func.count()).group_by(ScheduledPost.status)
            ).all()
        )
        rows = s.scalars(
            select(ScheduledPost).order_by(ScheduledPost.scheduled_at).limit(limit)
        ).all()
        data = [(r.id, r.generated_post_id, r.channel_ref, r.status,
                 r.scheduled_at.isoformat() if r.scheduled_at else "",
                 f"{r.attempts}/{r.max_attempts}", (r.last_error or "")[:40]) for r in rows]

    if not counts:
        console.print("[yellow]Queue empty. Use `schedule-post` or `autoschedule`.[/yellow]")
        return
    console.print("  ".join(f"[bold]{k}[/bold]={v}" for k, v in sorted(counts.items())))
    t = Table(title="Posting queue")
    for col in ("id", "post", "channel", "status", "scheduled_at", "tries", "note"):
        t.add_column(col)
    for r in data:
        t.add_row(*(str(x) for x in r))
    console.print(t)


@app.command("cancel-scheduled")
def cancel_scheduled(scheduled_id: int = typer.Argument(..., help="Queue row id")) -> None:
    """Cancel a queued/retrying post (won't touch already-published ones)."""
    from src.db.models_automation import ScheduledPost, ScheduleStatus

    with session_scope() as s:
        row = s.get(ScheduledPost, scheduled_id)
        if row is None:
            console.print(f"[red]No queue row #{scheduled_id}.[/red]")
            raise typer.Exit(1)
        if row.status in (ScheduleStatus.PUBLISHED, ScheduleStatus.SENDING):
            console.print(f"[yellow]#{scheduled_id} is {row.status}; not cancelled.[/yellow]")
            return
        row.status = ScheduleStatus.CANCELLED
    console.print(f"[green]Cancelled queue row #{scheduled_id}.[/green]")


@app.command("automate")
def automate(
    once: bool = typer.Option(False, "--once", help="Process due items once and exit"),
    poll: int = typer.Option(30, "--poll", help="Seconds between polls (continuous mode)"),
) -> None:
    """Run the posting scheduler. Sends stay gated (admin rights + affiliate integration)."""
    from src.services.automation.scheduler import PostingScheduler

    sched = PostingScheduler(poll_interval_seconds=poll)
    if once:
        stats = sched.process_due()
        console.print(f"[green]Processed {stats['due']} due[/green]: "
                      f"{stats['published']} published, {stats['blocked']} blocked, "
                      f"{stats['retried']} retry, {stats['failed']} failed.")
        if stats["blocked"]:
            console.print("[dim]Blocked = the account lacks admin post rights, or affiliate "
                          "integration is pending. This is expected on a member account.[/dim]")
        return
    console.print(f"[green]Automation running[/green] (poll {poll}s). Press Ctrl-C to stop.")
    try:
        while True:
            sched.process_due()
            time.sleep(poll)
    except KeyboardInterrupt:
        console.print("stopped.")


def _print_job(job: CollectionJob) -> None:
    color = {"completed": "green", "skipped": "yellow", "failed": "red"}.get(job.status, "white")
    console.print(
        f"[{color}]job #{job.id} {job.job_type} -> {job.status}[/{color}] "
        f"(processed={job.records_processed} added={job.records_added} "
        f"updated={job.records_updated})"
    )
    if job.error_message:
        console.print(f"  reason: {job.error_message}")


if __name__ == "__main__":
    app()
