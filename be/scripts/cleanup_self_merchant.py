"""One-off data cleanup: strip the platform's own domain (grabon.in) and
self-promo/utility domains (WhatsApp, Telegram) out of merchant attribution.

Root cause: `link_resolution.py`'s generic domain-capture fallback used to
slugify ANY unresolved final-redirect domain into a `merchant_key`, with no
exclusion for the platform's own domain or WhatsApp/Telegram share links — so
posts ended up with `primary_merchant_key="grabon"` (or "whatsapp"), poisoning
the merchant mix fed into the growth planner (see
`CampaignPlanningEngine._merchant_allocation` -> `MERCHANT_MIX` -> the LLM
planner prompt). `link_resolution.py` now excludes these domains going forward
via `_SELF_DOMAINS` (short-circuits `_resolve_one` before the network fetch,
and `_capture_domain`'s fallback); this script cleans up rows that were
poisoned before that fix landed.

After running this (without --dry-run), re-run the link-resolution backfill so
real merchants (or None) get recomputed through the fixed logic:

    tgagent resolve-links

Usage:
    cd be
    python -m scripts.cleanup_self_merchant            # dry run: report counts only
    python -m scripts.cleanup_self_merchant --apply    # actually write the nulls/deletes
"""

from __future__ import annotations

import argparse
import re
import sys

sys.path.insert(0, "src")

import tldextract
from sqlalchemy import select

from src.db.models_normalization import DiscoveredDomain, ExtractedLink, NormalizedPost
from src.db.session import session_scope
from src.services.collection.link_resolution import _SELF_DOMAINS


def _self_merchant_keys() -> set[str]:
    """Re-derive the merchant_key slugs the (now-fixed) domain-capture fallback
    would have produced for each self-domain — exactly the same slug algorithm
    as `LinkResolutionEngine._capture_domain` — so cleanup targets precisely
    what the bug could have written, no guessing at extra keys."""
    keys: set[str] = set()
    for domain in _SELF_DOMAINS:
        ext = tldextract.extract(f"https://{domain}")
        if not ext.domain:
            continue
        slug = re.sub(r"[^a-z0-9]+", "_", ext.domain.lower()).strip("_")
        if slug:
            keys.add(slug)
    keys.add("grabon")  # explicit — the confirmed root-cause key, kept even if
    # the slug algorithm above were ever to change.
    return keys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually write the deletes/nulls. Without this flag, only reports counts.",
    )
    args = parser.parse_args()

    self_keys = _self_merchant_keys()
    print(f"Self-domain merchant_key candidates: {sorted(self_keys)}")
    print(f"Self domains: {sorted(_SELF_DOMAINS)}")

    with session_scope() as s:
        domain_rows = s.execute(
            select(DiscoveredDomain.domain, DiscoveredDomain.merchant_key, DiscoveredDomain.count)
            .where(DiscoveredDomain.domain.in_(_SELF_DOMAINS))
        ).all()
        link_ids = s.execute(
            select(ExtractedLink.id).where(ExtractedLink.merchant_key.in_(self_keys))
        ).all()
        post_ids = s.execute(
            select(NormalizedPost.id).where(NormalizedPost.primary_merchant_key.in_(self_keys))
        ).all()

        print(f"\nBEFORE:")
        print(f"  DiscoveredDomain rows to delete: {len(domain_rows)} -> {domain_rows}")
        print(f"  ExtractedLink rows to null (merchant_key in self set): {len(link_ids)}")
        print(f"  NormalizedPost rows to null (primary_merchant_key in self set): {len(post_ids)}")

        if not args.apply:
            print("\nDry run only (pass --apply to write changes). No changes made.")
            return

        n_domains = (
            s.query(DiscoveredDomain)
            .filter(DiscoveredDomain.domain.in_(_SELF_DOMAINS))
            .delete(synchronize_session=False)
        )
        n_links = (
            s.query(ExtractedLink)
            .filter(ExtractedLink.merchant_key.in_(self_keys))
            .update(
                {
                    ExtractedLink.merchant_key: None,
                    ExtractedLink.resolved_url: None,
                    ExtractedLink.resolution_status: None,
                    ExtractedLink.resolution_error: None,
                    ExtractedLink.resolution_attempts: 0,
                },
                synchronize_session=False,
            )
        )
        n_posts = (
            s.query(NormalizedPost)
            .filter(NormalizedPost.primary_merchant_key.in_(self_keys))
            .update(
                {
                    NormalizedPost.primary_merchant_key: None,
                    NormalizedPost.primary_merchant_confidence: None,
                },
                synchronize_session=False,
            )
        )

        print(f"\nAPPLIED:")
        print(f"  Deleted {n_domains} DiscoveredDomain row(s).")
        print(f"  Nulled merchant_key/resolution fields on {n_links} ExtractedLink row(s).")
        print(f"  Nulled primary_merchant_key/confidence on {n_posts} NormalizedPost row(s).")
        print("\nNow re-run the backfill so real merchants get recomputed: tgagent resolve-links")


if __name__ == "__main__":
    main()
