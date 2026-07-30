# Spec — Slot mix enforcement (no more "a whole window is one merchant")

## The reported defect

> "it is planning mrg slot 9-11am only flipkart posts, nothing else ... it is only
> planning 1 brand for a 4-5 hr slot. there should be a mix of posts."

## Root cause — verified against live `be/data/tgagent.db`, not inferred

Query over the last 60 `generated_posts` (planned merchant/theme vs what actually filled):

```
planned flipkart · home-and-living          -> actual myntra   tier=any
planned flipkart · home-and-living          -> actual myntra   tier=any
planned flipkart · home-and-living          -> actual myntra   tier=any
planned ajio     · beauty-and-personal-care -> actual myntra   tier=any
planned ajio     · beauty-and-personal-care -> actual flipkart tier=any
planned ajio     · beauty-and-personal-care -> actual myntra   tier=any
planned ajio     · beauty-and-personal-care -> actual myntra   tier=any
planned ajio     · beauty-and-personal-care -> actual myntra   tier=any
planned ajio     · beauty-and-personal-care -> actual myntra   tier=any
```
fill tier distribution: `multi_category 28 · any 18 · exact 13` — **18/59 single-deal
fills (31%) matched neither the planned theme nor the planned merchant.**

Two independent layers are broken, and neither is the LLM:

**BUG 1 — fill-time has no memory (`services/generation/jit_fill.py:216 _pick_fresh`).**
It broadens `exact (theme+merchant) -> theme -> any`. Tier `any` returns the first unused
item from a pool that is ordered best-first (discount-desc), so whichever merchant holds
the deepest discounts that hour wins *every* broadened slot. There is no merchant tier
between `theme` and `any`, and no awareness of what the previous post used.
Compounding it: `jit_fill` is a **1-minute cron with a 3-min lookahead**, so consecutive
slots fill in *separate process invocations*. The in-run `used` set and the
`single_variant` rotation counter both reset every tick — the only cross-tick state is
`recently_used_urls(s)`, which dedups URLs but says nothing about merchant or category.
**So diversity state must be read from the DB, not held in the loop.**
(The loot path `_pick_fresh_multi` already round-robins merchants correctly — that is the
pattern to mirror, and why `multi_category` fills look fine in the data above.)

**BUG 2 — plan-time rotates merchants but not themes (`ai/planner.py:33
_repair_merchant_diversity`).** It enforces `_MAX_MERCHANT_SHARE` and "not the same
merchant as the previous slot in this window", but nothing does the same for `theme`. The
plan above put `beauty-and-personal-care` on 6 consecutive slots. It also no-ops entirely
when `available_merchants` has fewer than 2 entries.

**Not a bug — do not "fix" it:** the 4-merchant restriction is already enforced in three
places (`collection/deal_scraper.py:33 ALLOWED_MERCHANTS`, the per-retailer source query
in `generation/deal_source.py`, and the allowlist filter in `ai/context.py:available_deals`).
Nothing outside amazon/flipkart/myntra/ajio can reach a post. Leave it alone.

## Acceptance criteria

**AC1 — fill-time diversity state, read from the DB.** A helper returns, for a given IST
day, the merchant and theme/category counts of the posts already generated that day plus
the most recent one's merchant and category — sourced from `GeneratedPost.format_meta`
(`primary_merchant`, `slot.theme`), which jit_fill already writes. Unit-tested.

**AC2 — `_pick_fresh` becomes diversity-aware.** New signature takes the day's merchant
and category counts and the previous post's merchant/category. Behaviour:
- Tier order becomes `exact -> theme -> merchant -> any` (the `merchant` tier — planned
  merchant, any category — is new; today a merchant miss falls straight to `any`, which is
  the direct cause of the reported symptom).
- **Within every tier**, candidates are ordered by least-used merchant first, then
  least-used category, then the pool's existing best-first order as the tiebreak. The pool
  order alone must never decide a broadened pick again.
- A candidate whose merchant equals the immediately-previous post's merchant is used only
  when no alternative merchant exists in that tier. Same rule for category.
- The returned tier string still records what actually matched, so a broadened fill stays
  visible in `format_meta.match` and the log line.
- Degrades correctly: a pool genuinely carrying one merchant still fills (no slot is ever
  dropped for diversity — an unfilled slot is worse than a repeated merchant).

**AC3 — plan-time theme rotation.** `_repair_merchant_diversity` (rename it to reflect that
it now balances both dimensions) additionally prevents two adjacent slots in the same
window from carrying the same `theme` when the day's available deals offer another
category, reassigning the fewest slots possible. As with the merchant repair, a reassigned
slot's `why` is rewritten so the prose can't contradict the reassignment. No-ops with <2
available categories.

**AC4 — the mix is observable.** `fill_due_slots`'s return value reports the merchant and
category spread of what it filled (not just per-slot rows), and the existing broaden log
line states which tier and why, so "one merchant took the window" is visible in the run
record instead of needing a DB query to find.

**AC5 — regression tests that would have caught this.** Tests in `be/tests/` that:
- reproduce the exact failure above — a discount-desc pool dominated by one merchant, a
  sequence of slots planned for *other* merchants, filled one at a time with DB-backed
  state — and assert no merchant takes more than half the window;
- assert the new `merchant` tier is chosen before `any`;
- assert plan-time theme rotation breaks a 6-in-a-row identical-theme window.

**AC6 — gate green.** `loops/01-ship/scripts/gate.sh` exits 0. No test skipped or deleted.

## Out of scope
Do not touch the merchant allowlist, the loot path's existing round-robin, or the
`available_deals` menu diversification — all three are already correct.
