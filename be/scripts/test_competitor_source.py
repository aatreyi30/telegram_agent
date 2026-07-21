"""PROOF OF CONCEPT: source deals from COMPETITOR posts instead of the GrabCash API.

Pulls resolved competitor links already in the DB (competitor_posts -> extracted_links
with a known merchant), recovers the real product URL, swaps in OUR GrabOn affiliate
link, and formats them into our own posts with the existing PostFormatter.

No GrabCash API, no Groq, no office network needed -- it runs entirely off data already
collected. This is the "easy + trusted" sourcing path: real deals other channels vetted,
reposted under our affiliate links.

    python scripts/test_competitor_source.py                  # show the pool + sample posts
    python scripts/test_competitor_source.py --dev-chat -5291594307   # also send to a test chat
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402
from src.db.session import session_scope  # noqa: E402
from src.db.models_normalization import ExtractedLink, NormalizedPost, SourceType  # noqa: E402
from src.db.models_generation import EnrichedDeal  # noqa: E402
from src.services.affiliate import get_affiliate_provider  # noqa: E402
from src.services.collection.merchants.registry import detect_merchant_key  # noqa: E402
from src.services.generation.formatting import PostFormatter, DEFAULT_POST_TEMPLATES, pretty_category  # noqa: E402
from src.db.org_seed import get_default_org  # noqa: E402

ALLOWED = {"amazon", "flipkart", "myntra", "ajio"}


def _product_url(resolved: str | None, raw: str) -> str:
    """The clean merchant product URL to affiliate-ize. If the resolved URL is an
    affiliate redirector carrying the destination in a query param (e.g. affinity ?d=),
    recover that; else use the resolved URL if it's already a merchant, else the raw."""
    def _clean(u: str) -> str:
        # drop the competitor's tracking query (cuelinks/utm/etc.) -> bare product URL;
        # our affiliate provider re-adds our own params from the clean path.
        p = urlsplit(u)
        return f"{p.scheme}://{p.netloc}{p.path}"

    for candidate in (resolved, raw):
        if not candidate:
            continue
        if detect_merchant_key(candidate):
            return _clean(candidate)
        for vals in parse_qs(urlsplit(candidate).query).values():
            for v in vals:
                d = unquote(v)
                if d.startswith("http") and detect_merchant_key(d):
                    return _clean(d)
    return _clean(resolved or raw)


def _label(product_url: str, merchant: str) -> str:
    """A readable category/product label from the URL path (myntra.com/tops -> 'Tops'),
    falling back to the merchant name for opaque paths (amazon /dp/<asin>)."""
    parts = [p for p in urlsplit(product_url).path.split("/") if p and not p.startswith("dp")]
    seg = next((p for p in parts if p not in ("p", "buy", "gp", "product") and not p.isdigit()
                and len(p) > 2 and not p.isalnum() or (p and "-" in p)), None)
    return pretty_category(seg, pretty_category(merchant, "Deal")) if seg else pretty_category(merchant, "Deal")


def build_pool(limit: int = 400) -> list[dict]:
    """The competitor-sourced deal pool: {merchant, label, product_url, source_text}.
    ``source_text`` is the competitor's ORIGINAL post text — the real product name,
    specs and price live there, so the AI can rewrite a proper post from it."""
    from src.db.models import CompetitorPost
    with session_scope() as s:
        rows = s.execute(
            select(ExtractedLink.merchant_key, ExtractedLink.resolved_url, ExtractedLink.url,
                   CompetitorPost.text)
            .join(NormalizedPost, NormalizedPost.id == ExtractedLink.normalized_post_id)
            .join(CompetitorPost, CompetitorPost.id == NormalizedPost.source_id)
            .where(NormalizedPost.source_type == SourceType.COMPETITOR,
                   ExtractedLink.merchant_key.in_(ALLOWED))
            .limit(limit)
        ).all()
        pool, seen = [], set()
        for mk, resolved, raw, text in rows:
            product = _product_url(resolved, raw)
            if not product or product in seen:
                continue
            seen.add(product)
            pool.append({"merchant": mk, "label": _label(product, mk),
                         "product_url": product, "source_text": text or ""})
        return pool


def _deal(merchant, label, link, category) -> EnrichedDeal:
    return EnrichedDeal(title=label, category=category, current_price=None,
                        original_price=None, discount_percent=None, is_loot_deal=False,
                        tags=[], merchant_key=merchant, url=link, clean_url=link)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dev-chat", default=None, help="Also send the samples to this chat ref.")
    ap.add_argument("--limit", type=int, default=400)
    args = ap.parse_args()

    pool = build_pool(args.limit)
    from collections import Counter
    print(f"competitor-sourced pool: {len(pool)} unique deals")
    print("  by merchant:", dict(Counter(d["merchant"] for d in pool)))
    print()

    from src.ai.copywriter import Copywriter
    from src.ai.client import AIUnavailable
    from src.ai.context import channel_style

    # Load the org's real post_templates (with _deal_examples / _loot_examples) + channel
    # style + affiliate provider — this is exactly what the live jit_fill hands the AI,
    # so the prompt you're testing is the real one.
    with session_scope() as s:
        org = get_default_org(s)
        aff = get_affiliate_provider(org=org)
        templates = (org.settings or {}).get("post_templates") or dict(DEFAULT_POST_TEMPLATES)
        style = channel_style(s)
        cta, footer = templates.get("cta", ""), templates.get("footer", "")

    def _resolve(url: str) -> str:
        # follow a shortlink (amzn.to, fkrt.*, ...) to the real product URL so the
        # affiliate rule can attach OUR tag (amazon.in/dp/<ASIN>, flipkart .../p/...).
        try:
            with httpx.Client(follow_redirects=True, timeout=8, verify=False,
                              headers={"User-Agent": "Mozilla/5.0"}) as c:
                return str(c.get(url).url)
        except Exception:
            return url

    def _link(d):
        return aff.generate(_resolve(d["product_url"]), d["merchant"]).final_url  # OUR affiliate/short link

    writer = Copywriter()
    posts: list[tuple[str, str]] = []

    # LOOT via AI (write_for_loot): 5 distinct labels
    loot_items, seen_labels = [], set()
    for d in pool:
        if d["label"] in seen_labels:
            continue
        seen_labels.add(d["label"])
        loot_items.append({"label": d["label"], "link": _link(d)})
        if len(loot_items) >= 5:
            break
    if len(loot_items) >= 2:
        try:
            posts.append(("LOOT (AI-written)", writer.write_for_loot(
                loot_items, {"type": "collection"}, templates, style, cta=cta, footer=footer)))
        except (AIUnavailable, Exception) as e:  # noqa: BLE001
            posts.append(("LOOT (AI unavailable)", f"[{type(e).__name__}: {str(e)[:120]}]"))

    # DEALS via AI: REWRITE the competitor's own post text (which has the real product
    # name, specs and price) into our style + our link. This is the fix — the AI now has
    # real product info to write from, not just a bare URL.
    import json
    import re
    from src.ai.client import AIClient
    from src.ai.copywriter import assemble_post
    ai = AIClient()
    try:
        example = (json.loads(templates.get("_deal_examples") or "[]") or [""])[0]
    except Exception:
        example = ""
    rewrite_sys = (
        "You rewrite ONE deal from another Telegram channel into OUR channel's post.\n"
        "You are given the SOURCE post (it contains the real product NAME, key SPECS, and "
        "PRICE) and an EXAMPLE of our style.\n"
        "Rules: extract the real product name, a short specs line, and the price/discount "
        "from SOURCE — never invent them; omit any field SOURCE lacks. Write a short punchy "
        "hook, then the product name, then specs+price, then a CTA containing the token "
        "<link/> exactly once. We append the footer. One emoji max per line, hyphens not "
        "em-dashes.\nOutput ONLY:\n<hook>..</hook>\n<name>..</name>\n<price>..</price>\n"
        "<cta>..<link/>..</cta>"
    )
    def _clean_single(t: str) -> bool:
        # a real single-product deal post: exactly one price, a product-name line, not an
        # aggregator multi-deal dump (desidime/ddime), reasonable length.
        return (bool(re.search(r"₹\s*\d|\d+\s*Rs", t)) and t.count("₹") <= 1
                and 2 <= len(t.splitlines()) <= 12 and len(t) < 400
                and "ddime" not in t and "desidime" not in t and "|" not in t)

    rich = [d for d in pool if _clean_single(d["source_text"])][:3]
    for d in rich:
        print("===== DEAL — SOURCE (competitor post) =====")
        print(d["source_text"][:400])
        # Strip the competitor's links from the source so the AI can't copy THEIR link —
        # it must use the <link/> token, which we replace with OUR affiliate link. (No
        # plain-text example here: it makes the model mimic that plain format instead of
        # emitting the required tags.)
        src_clean = re.sub(r"https?://\S+", "", d["source_text"])
        user = f"SOURCE post:\n{src_clean[:800]}"
        try:
            raw = ai.complete(user, system_extra=rewrite_sys, max_tokens=400, effort="low")
            posts.append(("DEAL — REWRITTEN (ours)", assemble_post(raw, _link(d), footer)
                          or "[unparseable AI output]"))
        except (AIUnavailable, Exception) as e:  # noqa: BLE001
            posts.append(("DEAL (AI unavailable)", f"[{type(e).__name__}: {str(e)[:120]}]"))
        print(f"----- {posts[-1][0]} -----")
        print(posts[-1][1])
        print()

    for tag, p in posts:
        if tag.startswith("LOOT"):
            print(f"===== {tag} =====")
            print(p)
            print()

    if args.dev_chat:
        from src.services.generation.dev_send import dev_send
        for tag, p in posts:
            if not p.startswith("["):  # skip AI-failed placeholders
                print(dev_send(args.dev_chat, p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
