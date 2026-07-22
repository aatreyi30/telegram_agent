"""Post formatting: renders a Telegram-ready post from an enriched deal using the
channel's learned style and editable templates. Unknown fields are omitted (never
placeholder-filled). Links are tracked via an optional AffiliateProvider, or used
clean/untracked when none is set. The formatter never fabricates links."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models_generation import EnrichedDeal
from src.db.models_growth import GROWTH_VERSION, GrowthStrategy
from src.db.models_learning import LEARNING_VERSION, ChannelStyleProfile
from src.services.analytics.periods import ist_today, to_ist


# Editable post templates (org.settings["post_templates"] overrides these defaults).
# loot_* keys are price-free ("<Category> - <link>") and kept separate from the
# price/rank-bearing collection_* keys so neither leaks the other's placeholders.
DEFAULT_POST_TEMPLATES: dict[str, str] = {
    "single_loot_badge": "🔥 Loot price - limited time",
    "single_price": "{price} ({discount}% off from {mrp})",
    "single_coupon_line": "Use code {code}",
    "collection_theme_default": "Top Deals Today",
    "collection_item": "• {title}{price}\n  {link}",
    "collection_footer": "",
    "loot_theme_default": "{category} Loot Deals 🔥",
    "loot_price_subtitle": "Under ₹{cap}",
    "loot_item": "{title} - {link}",
    # Summary line under a loot list ("Best Deals on Fashion, Beauty & Essentials 🛒🔥").
    # Empty by default: the AI copywriter writes its own from the real categories, so
    # this only fires on the deterministic fallback, where an operator can opt in.
    "loot_closing": "",
    "cta": "Shop Now 👆",
    "footer": "🔁 Share • @GrabOnIndiaOfficial - 50+ loots daily",
    "category_theme_with_tier": "{emoji_start} {label} Under ₹{tier} {emoji_end}",
    "category_theme_no_tier": "{emoji_start} {label} Deals {emoji_end}",
    "category_item": "{title}{price}{coupon} - {link}",
    "category_coupon_suffix": " (code {code})",
    "observed_collection_theme": "Top Loot Deals",
    "fallback_category_label": "Top Deals",
    "fallback_title": "Deal",
}

# Keycap-emoji rank markers for a numbered loot list (1️⃣…🔟), matching the
# playbook's "Anchor — Top 10 Loot" format. Beyond 10 items, falls back to "11."
_RANK_MARKERS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


def _rank_marker(index: int) -> str:
    return _RANK_MARKERS[index] if index < len(_RANK_MARKERS) else f"{index + 1}."


def _fmt_verified_time(dt) -> str:
    """Human time-of-day a deal was last verified, in IST. Never fabricated —
    falls back to the word 'today' when we don't actually have a timestamp."""
    if not dt:
        return "today"
    s = to_ist(dt).strftime("%I:%M %p")
    return s.lstrip("0") or s


def _today_str() -> str:
    return ist_today().strftime("%d %b")


def _fmt_price(v: float | None) -> str | None:
    if v is None:
        return None
    return f"₹{int(v):,}" if float(v).is_integer() else f"₹{v:,.2f}"


_PRICE_TIERS = [100, 200, 300, 500, 700, 1000, 1500, 2000, 3000, 5000, 10000, 20000, 50000]


def price_tier(max_price: float | None) -> int | None:
    if max_price is None:
        return None
    return next((t for t in _PRICE_TIERS if max_price <= t), None)


def pretty_category(key: str | None, fallback: str = "Top Deals") -> str:
    if not key:
        return fallback
    return key.replace("-and-", " & ").replace("_", " ").replace("-", " ").title()


def _short_title(title: str | None, max_len: int = 60, fallback: str = "Deal") -> str:
    """Trim verbose retailer titles to a clean product name at a word boundary."""
    if not title:
        return fallback
    t = title.split("|")[0].split(" - ")[0].strip()  # drop marketing sub-clauses
    if len(t) <= max_len:
        return t
    cut = t[:max_len].rsplit(" ", 1)[0]
    return cut + "…"


# Loot lines are "<label> - <link>". A label this long keeps most lines on one row on
# mobile while still allowing natural names like "Perfumes for Men & Women" (which wrap)
# — the real channel's loot boards wrap a few lines, not all of them.
_LOOT_LABEL_MAX = 26


def _loot_label(category: str | None, fallback: str) -> str:
    """A tight category label for a loot line — capped at a word boundary, no ellipsis."""
    label = pretty_category(category, fallback)
    if len(label) <= _LOOT_LABEL_MAX:
        return label
    return label[:_LOOT_LABEL_MAX].rsplit(" ", 1)[0].rstrip(" &-") or label[:_LOOT_LABEL_MAX]


class PostFormatter:
    def __init__(self, session: Session, affiliate_provider=None, strategy=None,
                 templates: dict | None = None):
        self.affiliate = affiliate_provider  # None -> clean, untracked URLs
        self.templates = {**DEFAULT_POST_TEMPLATES, **(templates or {})}
        self.strategy = strategy
        style = session.scalar(
            select(ChannelStyleProfile).where(
                ChannelStyleProfile.learning_version == LEARNING_VERSION)
        )
        strat = session.scalar(
            select(GrowthStrategy).where(GrowthStrategy.growth_version == GROWTH_VERSION)
        )
        # Lead emoji: prefer ones the channel learned perform well over merely-frequent.
        performing = (list(self.strategy.lead_emojis) if self.strategy
                      else list((strat.blueprint or {}).get("emoji_strategy") or []) if strat else [])
        frequent = [e for e, _ in (style.top_emojis or [])] if style else []
        self.lead_emojis = (performing or frequent)[:2]
        self.uses_emoji = bool(style and (style.avg_emojis or 0) >= 1)
        # CTA + share footer are editable templates — clean by construction.
        self.cta_line = self.templates.get("cta", "")
        self.footer_line = self.templates.get("footer", "")

    def _render(self, key: str, **values) -> str:
        """Render a post template by key with ``values``, NEVER raising.

        A user can edit templates in Settings, so a template may reference an
        unknown placeholder, contain a stray brace, or not even be a string. On
        any such failure we fall back to the hardcoded DEFAULT_POST_TEMPLATES
        entry for that key (rendered with the same values) so post generation
        can never be crashed by a bad edit."""
        template = self.templates.get(key, DEFAULT_POST_TEMPLATES[key])
        try:
            return template.format_map(values)
        except (KeyError, ValueError, IndexError, AttributeError, TypeError):
            default = DEFAULT_POST_TEMPLATES[key]
            try:
                return default.format_map(values)
            except (KeyError, ValueError, IndexError, AttributeError, TypeError):
                return default

    def _finish(self, rendered: str, meta: dict) -> tuple[str, dict]:
        return rendered.strip(), {**meta, "lead_emojis": self.lead_emojis}

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
        title = deal.title or self._render("fallback_title")
        lines.append(f"{emoji} {title}".strip())

        # price highlight (only what we actually know)
        price_bits = []
        cur = _fmt_price(deal.current_price)
        mrp = _fmt_price(deal.original_price)
        if cur and mrp and deal.discount_percent:
            price_bits.append(self._render("single_price", price=cur, mrp=mrp,
                                           discount=f"{deal.discount_percent:.0f}"))
        elif cur:
            price_bits.append(cur)
        if price_bits:
            lines.append(price_bits[0])

        if deal.is_loot_deal:
            lines.append(self._render("single_loot_badge"))

        # coupon proof line — only when this deal actually carries a coupon tag
        # (tags entries of the form "coupon:<code>"); never fabricated, and the
        # template defaults to "" so this is a no-op until an operator opts in.
        code = next((t.split(":", 1)[1] for t in (deal.tags or [])
                    if isinstance(t, str) and t.startswith("coupon:")), None)
        if code:
            coupon_line = self._render("single_coupon_line", code=code,
                                       time=_fmt_verified_time(deal.last_verified_at),
                                       date=_today_str())
            if coupon_line.strip():
                lines.append(coupon_line)

        # link: affiliate/short link if a provider is configured, else clean URL
        link, aff_meta = self._finalize_link(deal)
        if link:
            lines.append(f"👉 {link}")

        # learned share footer, so the fallback post is shaped like a real one
        if self.footer_line:
            lines.append(self.footer_line)

        # Blank line between every section — the real posts are spaced, not congested.
        # (This is the deterministic fallback; the AI path owns its own spacing.)
        rendered = "\n\n".join(lines)
        meta = {
            "used_emojis": self.lead_emojis,
            **aff_meta,
            "coupon_code": code,
            "fields_omitted_unknown": [k for k, v in
                                       {"current_price": deal.current_price,
                                        "original_price": deal.original_price,
                                        "discount_percent": deal.discount_percent}.items()
                                       if v is None],
        }
        return self._finish(rendered, meta)

    def format_collection(self, deals: list[EnrichedDeal], theme: str | None = None) -> tuple[str, dict]:
        emoji = " ".join(self.lead_emojis) if self.uses_emoji and self.lead_emojis else ""
        theme_text = theme or self._render("collection_theme_default", date=_today_str())
        header = f"{emoji} {theme_text}".strip()
        lines = [header, ""]
        shortened_any = False
        for i, d in enumerate(deals):
            cur = _fmt_price(d.current_price)
            title = d.title or self._render("fallback_title")
            link, aff_meta = self._finalize_link(d)
            shortened_any = shortened_any or aff_meta.get("affiliate_shortened", False)
            link = link or ""
            price = f" — {cur}" if cur else ""
            discount = f"{d.discount_percent:.0f}" if d.discount_percent is not None else ""
            lines.append(self._render("collection_item", n=_rank_marker(i), title=title,
                                      price=price, raw_price=cur or "", discount=discount,
                                      link=link).rstrip())
        # optional closing footer (e.g. "🔔 Notifications ON") — off by default
        footer = self._render("collection_footer")
        if footer.strip():
            lines.append("")
            lines.append(footer)
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
        lines.append(candidate.theme or self._render("observed_collection_theme"))
        lines.append("")
        for it in candidate.items:
            name = it.name or self._render("fallback_title")
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
        label = pretty_category(category_key, self._render("fallback_category_label"))
        prices = [d.current_price for d in deals if d.current_price is not None]
        tier = price_tier(max(prices)) if prices else None
        if tier:
            theme = self._render("category_theme_with_tier", emoji_start=e1, label=label,
                                 tier=tier, emoji_end=e2).strip()
        else:
            theme = self._render("category_theme_no_tier", emoji_start=e1, label=label,
                                 emoji_end=e2).strip()

        lines = [theme, ""]
        shortened_any = False
        for d in deals:
            title = _short_title(d.title, fallback=self._render("fallback_title"))
            link, aff_meta = self._finalize_link(d)
            shortened_any = shortened_any or aff_meta.get("affiliate_shortened", False)
            link = link or ""
            cur = _fmt_price(d.current_price)
            price = f" @ {cur}" if cur else ""
            coupon = ""
            for tag in (d.tags or []):
                if isinstance(tag, str) and tag.startswith("coupon:"):
                    coupon = self._render("category_coupon_suffix", code=tag.split(':', 1)[1])
            lines.append(self._render("category_item", title=title, price=price,
                                      coupon=coupon, link=link))
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

    def format_multi_category_loot(self, deals: list[EnrichedDeal], theme: str | None = None,
                                   price_cap: float | None = None,
                                   price_floor: float | None = None) -> tuple[str, dict]:
        """A loot post: several DIFFERENT categories bundled under one theme, one bare
        '<Category> - <link>' line each — no price, no per-item copy, no AI. Labels are
        kept tight so the link doesn't wrap on mobile. An optional ``price_cap`` adds an
        'Under ₹X' subtitle for price-tier loots."""
        seen_categories: set[str] = set()
        category_order: list[str] = []
        item_lines: list[str] = []
        shortened_any = False
        for d in deals:
            label = _loot_label(d.category, self._render("fallback_category_label"))
            if label in seen_categories:
                continue  # one line per distinct category
            seen_categories.add(label)
            category_order.append(label)
            link, aff_meta = self._finalize_link(d)
            shortened_any = shortened_any or aff_meta.get("affiliate_shortened", False)
            item_lines.append(self._render("loot_item", title=label, link=link or "").rstrip())

        # Theme: explicit slot theme wins, else the first-category template (emoji baked in).
        # A price cap adds an "Under ₹X" subtitle directly under the theme line.
        theme_text = theme or self._render("loot_theme_default",
                                           category=category_order[0] if category_order else "",
                                           date=_today_str())
        header = [theme_text.strip()]
        if price_cap and price_floor:
            header.append(f"₹{int(price_floor):,}–₹{int(price_cap):,}")
        elif price_cap:
            header.append(self._render("loot_price_subtitle", cap=f"{int(price_cap):,}"))
        lines = [*header, "", *item_lines]
        closing = self._render("loot_closing", categories=", ".join(category_order))
        if closing.strip():
            lines.append("")
            lines.append(closing)
        lines.append("")
        if self.cta_line:
            lines.append(self.cta_line)
        if self.footer_line:
            lines.append(self.footer_line)
        rendered = "\n".join(lines).rstrip()
        meta = {"kind": "multi_category_loot", "categories": sorted(seen_categories),
                "item_count": len(seen_categories), "price_cap": price_cap,
                "price_floor": price_floor,
                "affiliate_status": (f"{self.affiliate.name}_applied" if self.affiliate
                                     else "no_provider_clean_url"),
                "affiliate_shortened_any": shortened_any, "links_real_fresh": True}
        return self._finish(rendered, meta)

    def format_observed_single(self, candidate) -> tuple[str, dict]:
        it = candidate.items[0]
        emoji = " ".join(self.lead_emojis) if self.uses_emoji and self.lead_emojis else ""
        title = it.name or (candidate.theme or self._render("fallback_title"))
        lines = [f"{emoji} {title}".strip(), it.url]
        if self.cta_line:
            lines.append(self.cta_line)
        if self.footer_line:
            lines.append(self.footer_line)
        rendered = "\n".join(lines)
        meta = {"kind": "single", "links_real_observed": True,
                "affiliate_status": "deferred_clean_url_used"}
        return self._finish(rendered, meta)
