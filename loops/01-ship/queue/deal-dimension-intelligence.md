# Spec — Deal-dimension intelligence (PRODUCT_GAP_ANALYSIS Track A)

## Why

`PRODUCT_GAP_ANALYSIS.md` §10 (the ~50-defect numeric ledger) is fixed and the gate is
green on it. What remains is **Track A / §0.5** — the reason the product still feels
hollow even when everything renders:

> "The only outcome signal it uses is channel-average VIEWS ... performance is never
> attributed to any deal dimension, because category/price never lands on a measured
> post ... competitor intelligence is style-only, not deal-level."

Proof in live data (`be/data/tgagent.db`):
- `normalized_posts` has `primary_merchant_key` but **no category, no discount, no price band**
  (`PRAGMA table_info` — confirmed).
- Every slot `why` in daily plan id 10 cites the same number (`206.1 avg views/day`) for
  fashion, electronics, beauty alike.
- The raw material is right there in the post text — verified samples:
  `'boAt Airdopes 212 ... ₹799 (76% OFF)'`, `'Towel Essentials Loot 💥 Under ₹500'`,
  `'EXODUS Water Bottle ... Deal Price ₹80 You Save 84%'`.

So: extract the dimensions that are already in the text, measure engagement per dimension,
and feed those numbers to the planner and the screens. Zero new permissions, zero new
data sources.

## Out of scope (deliberate, stated in PR body)

- `/r/{id}` click tracker (§4.3) — a monetization build + deploy decision, not analytics.
- Channel split-brain / admin rights (§4.1) — a human decision about which channel is truth.
- Wiring `DealRanker` into the scheduled path + merchant-allocator exploration (§3.5/3.6) —
  already mitigated by the `available_deals` merchant round-robin that shipped.

## Acceptance criteria (all testable)

**AC1 — deterministic dimension extraction.** `src/services/processing/parser.py` gains
pure functions, each with unit tests over the real post-text shapes above:
- `parse_discount_pct(text) -> float | None` — handles `76% OFF`, `You Save 84%`,
  `Flat 50% off`; returns `None` when absent; ignores implausible values (`>=100`, `<=0`).
- `discount_band(pct) -> str | None` — fixed bands: `70%+`, `50-69%`, `30-49%`, `<30%`.
- `price_band(prices, threshold) -> str | None` — `under-299`, `300-499`, `500-999`,
  `1000-2999`, `3000+`, derived from the stated deal price (or the "under ₹X" ceiling
  when that's all the post states). `None` when no price is stated.
- `infer_category(text, merchant_key) -> str | None` — deterministic keyword table
  emitting **the same taxonomy as `enriched_deals.category`**
  (`fashion-and-lifestyle`, `electronics-and-gadgets`, `beauty-and-personal-care`,
  `home-and-living`, `health-and-wellness`, `general`). Returns `None` — never `general`
  as a guess — when nothing matches, so coverage stays honest and measurable.

**AC2 — the dimensions land on measured posts.** `NormalizedPost` gains
`category`, `discount_pct`, `discount_band`, `price_band`; they are populated by
`PostNormalizer._normalize_one` for **both** owned and competitor sources; the columns are
added to `db/migrate.py:_ADDITIONS`; `NORMALIZATION_VERSION` is bumped so the existing
~8k rows re-normalize on the next pass (no bespoke backfill script). A test asserts a
normalized post built from a real sample text carries the right category/band.

**AC3 — engagement-rate leaderboards.** `services/analytics/views.py:compute()` returns
`by_category`, `by_discount_band`, `by_price_band` alongside the existing dimensions,
each bucket carrying the existing `_reduce` shape (n, avg/median views, engagement_rate).
Plus a `segments` list: the dimension buckets ranked by **engagement rate** (reactions+forwards
÷ views), gated at a minimum sample size, each row labelled with its dimension and `n`.
Buckets below the gate are excluded, and the payload states the gate so the UI can say
"not enough data" instead of showing noise.

**AC4 — competitor deal-gap.** A new deterministic module computes, over one window,
per-category **share of posts** for owned vs tracked competitors, and flags categories where
competitors over-index and we're absent/under-indexed. Exposed on the existing competitor
dashboard payload. Only categories with a real sample on the competitor side are reported.

**AC5 — the plan cites dimension evidence, not the channel average.**
`build_plan_context` gains a `segment_performance` block (top/bottom categories and discount
bands by engagement rate, with n). Its numbers are added to the `facts` pool so the existing
deterministic factcheck verifies anything the model cites from it. The daily-plan prompt
requires each slot's `why` to cite a **dimension-level** number when one is available,
instead of restating the channel average.

**AC6 — it's visible.** `/analytics` renders the segment leaderboards (with the
insufficient-data state) and `/competitors` renders the deal-gap. Types updated in
`next/types/api.ts`.

**AC7 — the gate stays green.** `loops/01-ship/scripts/gate.sh` exits 0 (pytest + tsc).
No test deleted or skipped; no existing behaviour silently changed beyond the additions above.
