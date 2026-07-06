"""Post Formatting (source_truth/04 Phase 9).

Renders a Telegram-ready post from an enriched deal using the channel's LEARNED
style (Phase 6 ChannelStyleProfile: top-performing emojis, caption tendencies) —
NOT a hardcoded template (RULE 3). The structure is assembled from learned style
parameters + the deal's known fields; unknown fields are simply omitted (never
filled with placeholders).

Affiliate/tracking link injection is handled by an optional AffiliateProvider
(tgagent/affiliate/). When one is configured (e.g. GrabOn), each product link is
converted to its affiliate/short URL; when none is set, the clean product URL is
used and flagged as untracked. The formatter never fabricates links.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Post
from src.db.models_generation import EnrichedDeal
from src.db.models_growth import GROWTH_VERSION, GrowthStrategy
from src.db.models_learning import LEARNING_VERSION, ChannelStyleProfile
from src.db.models_normalization import NormalizedPost, SourceType


def _fmt_price(v: float | None) -> str | None:
    if v is None:
        return None
    return f"₹{int(v):,}" if float(v).is_integer() else f"₹{v:,.2f}"


_PRICE_TIERS = [100, 200, 300, 500, 700, 1000, 1500, 2000, 3000, 5000, 10000, 20000, 50000]


def price_tier(max_price: float | None) -> int | None:
    if max_price is None:
        return None
    return next((t for t in _PRICE_TIERS if max_price <= t), None)


def pretty_category(key: str | None) -> str:
    if not key:
        return "Top Deals"
    return key.replace("-and-", " & ").replace("_", " ").replace("-", " ").title()


def strip_emojis(text: str | None, avoid: set[str]) -> str:
    """Remove every avoid-list emoji from text, then tidy leftover whitespace.

    Enforces the learned emoji policy even inside learned CTA/footer lines (e.g.
    'Shop Now 😍👆' -> 'Shop Now 👆'). Newlines are preserved; only runs of spaces
    are collapsed."""
    if not text or not avoid:
        return text or ""
    for e in avoid:
        text = text.replace(e, "")
    # collapse spaces/tabs (not newlines), trim each line
    lines = [" ".join(ln.split()) for ln in text.split("\n")]
    return "\n".join(lines).strip()


def _short_title(title: str | None, max_len: int = 60) -> str:
    """Trim verbose retailer titles to a clean product name at a word boundary."""
    if not title:
        return "Deal"
    t = title.split("|")[0].split(" - ")[0].strip()  # drop marketing sub-clauses
    if len(t) <= max_len:
        return t
    cut = t[:max_len].rsplit(" ", 1)[0]
    return cut + "…"


class PostFormatter:
    def __init__(self, session: Session, affiliate_provider=None, strategy=None):
        # Optional AffiliateProvider — converts product URLs to tracked/short links.
        # None -> clean URLs are used unchanged (untracked).
        self.affiliate = affiliate_provider
        # Optional PostingStrategy — enforces the learned emoji policy (lead + avoid).
        self.strategy = strategy
        self.avoid_emojis = set(strategy.avoid_emojis) if strategy else set()
        style = session.scalar(
            select(ChannelStyleProfile).where(
                ChannelStyleProfile.learning_version == LEARNING_VERSION)
        )
        # Prefer emojis the channel learned PERFORM well (Growth blueprint), not the
        # merely most-frequent ones — leading with an emoji we know underperforms
        # would contradict the learning. Fall back to frequent emojis, then none.
        strat = session.scalar(
            select(GrowthStrategy).where(GrowthStrategy.growth_version == GROWTH_VERSION)
        )
        performing = (list(self.strategy.lead_emojis) if self.strategy
                      else list((strat.blueprint or {}).get("emoji_strategy") or []) if strat else [])
        frequent = [e for e, _ in (style.top_emojis or [])] if style else []
        # never lead with an avoid-emoji, even if it's frequent
        candidates = [e for e in (performing or frequent) if e not in self.avoid_emojis]
        self.lead_emojis = candidates[:2]
        self.uses_emoji = bool(style and (style.avg_emojis or 0) >= 1)
        # learn the channel's real CTA line + share footer from its own posts,
        # then STRIP any avoid-emoji so learned lines can't reintroduce them
        cta, footer = self._learn_signature(session)
        self.cta_line = strip_emojis(cta, self.avoid_emojis) or cta
        self.footer_line = strip_emojis(footer, self.avoid_emojis) or footer

    @staticmethod
    def _learn_signature(session: Session) -> tuple[str | None, str | None]:
        """Derive the channel's most common CTA line and share footer from its
        own post history (learned, not hardcoded)."""
        texts = session.execute(
            select(Post.text)
            .join(NormalizedPost, NormalizedPost.source_id == Post.id)
            .where(NormalizedPost.source_type == SourceType.OWNED, Post.text.isnot(None))
            .limit(800)
        ).all()
        cta_c: Counter = Counter()
        foot_c: Counter = Counter()
        for (t,) in texts:
            for ln in (t or "").splitlines():
                s = ln.strip()
                if not s or s.startswith("http"):
                    continue
                low = s.lower()
                if len(s) <= 30 and (any(k in low for k in
                        ("shop now", "grab", "buy now", "order", "shop here", "get it"))
                        or "👆" in s or "👉" in s):
                    cta_c[s] += 1
                if len(s) <= 70 and ("share" in low or s.startswith("📲") or "@" in s):
                    foot_c[s] += 1
        cta = cta_c.most_common(1)[0][0] if cta_c else None
        footer = foot_c.most_common(1)[0][0] if foot_c else None
        return cta, footer

    def _finish(self, rendered: str, meta: dict) -> tuple[str, dict]:
        """Final guard: strip any avoid-emoji from the whole post and record the
        emoji policy that was applied (so the draft can prove it followed strategy)."""
        rendered = strip_emojis(rendered, self.avoid_emojis)
        meta = {**meta, "emoji_policy": {"lead": self.lead_emojis,
                                         "avoided": sorted(self.avoid_emojis)}}
        return rendered, meta

    def _finalize_link(self, deal: EnrichedDeal) -> tuple[str | None, dict]:
        """Return (link_to_use, affiliate_meta) for a deal.

        With an AffiliateProvider configured, the ORIGINAL product URL (which
        carries the merchant path, e.g. /dp/<id>) is turned into the affiliate/
        short link. Without one, the clean URL is used untracked.
        """
        raw = deal.url or deal.clean_url
        if self.affiliate is None or not raw:
            return (deal.clean_url or deal.url), {"affiliate_status": "no_provider_clean_url"}
        res = self.affiliate.generate(raw, deal.merchant_key)
        return res.final_url, {"affiliate_status": f"{res.provider}_applied",
                               "affiliate_provider": res.provider,
                               "affiliate_shortened": res.shortened,
                               "affiliate_merchant": res.merchant_key,
                               "affiliate_notes": res.notes}

    def format_single(self, deal: EnrichedDeal) -> tuple[str, dict]:
        lines: list[str] = []
        emoji = " ".join(self.lead_emojis) if self.uses_emoji and self.lead_emojis else ""
        title = deal.title or "Deal"
        lines.append(f"{emoji} {title}".strip())

        # price highlight (only what we actually know)
        price_bits = []
        cur = _fmt_price(deal.current_price)
        mrp = _fmt_price(deal.original_price)
        if cur and mrp and deal.discount_percent:
            price_bits.append(f"{cur}  (was {mrp}, {deal.discount_percent:.0f}% off)")
        elif cur:
            price_bits.append(cur)
        if price_bits:
            lines.append(price_bits[0])

        if deal.is_loot_deal:
            lines.append("🔥 Loot price — limited time")

        # link: affiliate/short link if a provider is configured, else clean URL
        link, aff_meta = self._finalize_link(deal)
        if link:
            lines.append(link)

        rendered = "\n".join(lines)
        meta = {
            "used_emojis": self.lead_emojis,
            **aff_meta,
            "fields_omitted_unknown": [k for k, v in
                                       {"current_price": deal.current_price,
                                        "original_price": deal.original_price,
                                        "discount_percent": deal.discount_percent}.items()
                                       if v is None],
        }
        return self._finish(rendered, meta)

    def format_collection(self, deals: list[EnrichedDeal], theme: str | None = None) -> tuple[str, dict]:
        emoji = " ".join(self.lead_emojis) if self.uses_emoji and self.lead_emojis else ""
        header = f"{emoji} {theme or 'Top Deals Today'}".strip()
        lines = [header, ""]
        shortened_any = False
        for d in deals:
            cur = _fmt_price(d.current_price)
            title = d.title or "Deal"
            link, aff_meta = self._finalize_link(d)
            shortened_any = shortened_any or aff_meta.get("affiliate_shortened", False)
            link = link or ""
            price = f" — {cur}" if cur else ""
            lines.append(f"• {title}{price}\n  {link}".rstrip())
        rendered = "\n".join(lines)
        meta = {"used_emojis": self.lead_emojis, "item_count": len(deals),
                "affiliate_status": (f"{self.affiliate.name}_applied" if self.affiliate
                                     else "no_provider_clean_url"),
                "affiliate_shortened_any": shortened_any}
        return self._finish(rendered, meta)

    # ---- observed real-deal candidates (real links) ---------------------- #
    def format_observed_collection(self, candidate) -> tuple[str, dict]:
        """Themed multi-link loot collection, matching how the channel really
        posts them: theme line + product/link items + learned CTA + share footer.
        All links are the REAL observed grbn.in links (reachable)."""
        lines: list[str] = []
        lines.append(candidate.theme or "Top Loot Deals")
        lines.append("")
        for it in candidate.items:
            name = it.name or "Deal"
            lines.append(f"{name} - {it.url}")
        lines.append("")
        if self.cta_line:
            lines.append(self.cta_line)
        if self.footer_line:
            lines.append(self.footer_line)
        rendered = "\n".join(lines).rstrip()
        meta = {"kind": "loot_collection", "item_count": len(candidate.items),
                "cta_line": self.cta_line, "footer_line": self.footer_line,
                "links_real_observed": True, "affiliate_status": "deferred_clean_url_used"}
        return self._finish(rendered, meta)

    def format_category_collection(self, category_key: str, deals: list[EnrichedDeal]) -> tuple[str, dict]:
        """A fresh, category-themed loot collection from TODAY's deals — the
        channel's signature '<Category> Under ₹X' format, with real product links."""
        e1 = self.lead_emojis[0] if self.lead_emojis and self.uses_emoji else ""
        e2 = self.lead_emojis[1] if len(self.lead_emojis) > 1 and self.uses_emoji else ""
        label = pretty_category(category_key)
        prices = [d.current_price for d in deals if d.current_price is not None]
        tier = price_tier(max(prices)) if prices else None
        theme = f"{e1} {label} Under ₹{tier} {e2}".strip() if tier else f"{e1} {label} Deals {e2}".strip()

        lines = [theme, ""]
        shortened_any = False
        for d in deals:
            title = _short_title(d.title)
            link, aff_meta = self._finalize_link(d)
            shortened_any = shortened_any or aff_meta.get("affiliate_shortened", False)
            link = link or ""
            cur = _fmt_price(d.current_price)
            price = f" @ {cur}" if cur else ""
            coupon = ""
            for tag in (d.tags or []):
                if isinstance(tag, str) and tag.startswith("coupon:"):
                    coupon = f" (code {tag.split(':', 1)[1]})"
            lines.append(f"{title}{price}{coupon} - {link}")
        lines.append("")
        if self.cta_line:
            lines.append(self.cta_line)
        if self.footer_line:
            lines.append(self.footer_line)
        rendered = "\n".join(lines).rstrip()
        meta = {"kind": "category_collection", "category": category_key,
                "price_tier": tier, "item_count": len(deals),
                "affiliate_status": (f"{self.affiliate.name}_applied" if self.affiliate
                                     else "no_provider_clean_url"),
                "affiliate_shortened_any": shortened_any, "links_real_fresh": True}
        return self._finish(rendered, meta)

    def format_observed_single(self, candidate) -> tuple[str, dict]:
        it = candidate.items[0]
        emoji = " ".join(self.lead_emojis) if self.uses_emoji and self.lead_emojis else ""
        title = it.name or (candidate.theme or "Deal")
        lines = [f"{emoji} {title}".strip(), it.url]
        if self.cta_line:
            lines.append(self.cta_line)
        if self.footer_line:
            lines.append(self.footer_line)
        rendered = "\n".join(lines)
        meta = {"kind": "single", "links_real_observed": True,
                "affiliate_status": "deferred_clean_url_used"}
        return self._finish(rendered, meta)
