# Punchlist — trip 1 adversarial review returned BLOCK

Five S1 findings. Two of them are severe: **S1-d re-creates the exact defect all three specs
exist to remove**, and **S1-c silently destroys shortlink-resolution state for ~8k rows.**

Group by file scope so these can be fixed in parallel without collisions.

---

## GROUP A — `be/src/services/generation/jit_fill.py`

### [S1-a] The adjacency rule is not implemented; the reported defect still reproduces
`jit_fill.py:338-343` (`rank`). The prev-merchant penalty is the SECOND tuple element, so it
is subordinate to `merchant_counts`. A candidate matching the previous post's merchant wins
whenever its day-count is lower than every alternative's.

Reviewer reproduced by execution: `merchant_counts={'myntra':5,'flipkart':1}`, `prev='flipkart'`,
pool has both → 5 sequential picks give `['flipkart','flipkart','flipkart','flipkart','myntra']`.
**Four consecutive same-merchant fills with an alternative present in the same tier.**

Spec (slot-mix AC2) is explicit: *"A candidate whose merchant equals the immediately-previous
post's merchant is used only when no alternative merchant exists in that tier. Same rule for
category."* Make the prev-repeat penalty dominate the count ranking, not the reverse. Keep the
never-drop-a-slot guarantee: if the tier holds only the previous merchant, still fill.

**Test that fails today:** seed an UNEVEN `merchant_counts` (the existing test starts from an
empty dict, which is exactly why this was invisible) and assert no two consecutive picks share
a merchant while an alternative exists in the tier.

### [S1-b] The category half of the ranking is dead — counts keyed in the wrong vocabulary
`jit_fill.py:342` looks up `category_counts.get(c, 0)` with `c = it["category_key"]` (the deal
source's vocabulary), but `:308`/`:687` key the dict by `slot.theme` (the plan's vocabulary).
Same defect for merchant at `:340` vs `:684`/`:305`.

This file's own `_match`/`_norm` (`:165-178`) exist *because* those vocabularies differ
("amazon" vs "amazon_in"). Inside `rank`, `prev_merchant`/`prev_category` correctly use loose
`_match` while the counts use exact `dict.get` — so every category count reads 0 and half the
ranking is a constant.

Key every count through `_norm` on both the write and read side. Also: the tally records the
**planned** theme, not the theme actually filled, so a broadened fill is counted as a category
it isn't — record what was actually filled.

**Test:** a pool whose `category_key`/`merchant_key` differ in vocabulary from the planned
theme/merchant (e.g. `"Electronics"` vs `"electronics-and-gadgets"`) and still shows the
ranking working.

### [S2-b] `format_meta.slot` drops the per-post intent (per-post-planning AC3)
`jit_fill.py:659` records only `{theme, merchant}`. `type`, `time_ist`, `max_price`, `min_price`
are dropped — so the plan-vs-actual query that produced these specs' root-cause evidence cannot
be run on the new dimensions. Record the slot dict whole.

### [S3-e] `_day_mix` counts drafts from other engines
`jit_fill.py:296-301` windows on `GeneratedPost.generated_at` with no other filter, so drafts
from `controllers/jobs.py:132` / the CLI generator count toward jit_fill's tallies. Filter to
jit_fill's own drafts (the `selection_bucket` `aislot:` prefix is already the marker).

---

## GROUP B — `be/src/services/generation/ai_execution.py`, `be/src/ai/factcheck.py`

### [S1-d] Count reconciliation re-creates the reported defect — HIGHEST PRIORITY
`ai_execution.py:76-79` (`out.append(dict(have[-1]))`). Up-scaling duplicates the LAST slot of
the under-quota type repeatedly: same `time_ist`, same merchant, same theme, same `why`.
`_expand_slots`'s collision floor then fires them `SPACING_MIN` apart.

Reviewer reproduced by execution — 2 slots, target 7:
```
09:00 amazon/electronics ×3  -> fires 09:00, 09:02, 09:04
18:00 ajio/fashion       ×4  -> fires 18:00, 18:02, 18:04, 18:06
```
That is **verbatim the user's reported symptom**: one brand, dumped all at once, then silence.

It runs at persist time (`:152`) AFTER `_repair_plan_diversity` (`planner.py:594`), so nothing
rebalances the result. It triggers on the deterministic fallback too (`_fallback_day_plan`'s
per-window `max(round(...), 1)` routinely sums off `recommended_posts`) — not an AI-only edge.

Fix: duplicated slots must get their own spread time and rotate merchant/theme — or run the
diversity repair AFTER reconciliation. Preserve the existing contract: exact reconciled total,
chronological order, `_MIN_TYPE_SHARE` floor, `plan_clamped` flag, never an empty day.

**Test:** replace `test_per_post_planning.py:113-117`'s `len == 5` assertion with distinct fire
times AND no adjacent merchant/theme repeat. The current assertion passes while this ships.

### [S2-a] `time_ist` is missing from the factcheck's structural whitelist
`factcheck.py:51-56` whitelists `count`, `max_price`, `min_price` and the hours inside
`window_ist` as the plan's OWN numbers, which "restating in prose must never count as a
fabrication". `time_ist` was never added when it replaced `window_ist`.

The prompt now requires each `why` to justify timing (`prompts/daily_plan.py:151`), so
"posting at 09:05" yields ungrounded prose numbers 9.0 and 5.0. A `failed` status replaces the
digest with an error string AND refuses to fill the day (`service.py:955-961`,
`jit_fill.py:492-493`). Add `time_ist`'s hours to the structural pool.

**Test:** a per-post plan whose `why` quotes its own `time_ist` factchecks `passed`.

---

## GROUP C — `be/src/services/processing/normalizer.py`, `be/src/services/processing/parser.py`

### [S1-c] The `NORMALIZATION_VERSION` bump destroys link-resolution state for ~8k rows
`models_normalization.py:39` + `normalizer.py:152-154`, `:191-196`.

`_normalize_one` deletes the `NormalizedPost` and cascades (`cascade="all, delete-orphan"`)
into `extracted_links`, then recreates each link from the RAW url with
`merchant_key=detect_merchant_key(u)` — never writing `resolved_url`, `resolution_status`,
`resolution_error`, `resolution_attempts`. Those are populated only by the network resolver
(`link_resolution.py:437-447`).

Consequences: every re-normalized row loses its resolved merchant; `primary_merchant_key` falls
back to raw-domain detection, which is **NULL for every `grbn.in` shortlink** (i.e. most of the
corpus). The cross-run resolution cache is seeded from `resolved_url IS NOT NULL`
(`link_resolution.py:351-357`), so it empties too — the whole corpus must be re-resolved over
the network, with `resolution_attempts` reset to 0 so the retry cap no longer protects
permanently-dead links. `PostClassification` rows cascade away as well.

Merchant attribution is the denominator of `merchant_mix`, the MERCHANT_MIX plan facts,
`by_merchant` analytics and competitor merchant share — all silently degrade meanwhile.

Fix: carry the resolution columns forward from the existing row (or update in place instead of
delete + recreate). **Test:** normalize a post twice across a version bump and assert
`resolved_url`/`merchant_key`/`resolution_status`/`resolution_attempts` survive.

### [S2-c] `infer_category` guesses from merchant — the one thing AC1 forbade
`parser.py:313-320`, `:335-336`. AC1: *"Returns None — never `general` as a guess — when
nothing matches, so coverage stays honest and measurable."* `_MERCHANT_CATEGORY_HINTS` maps
myntra/ajio → fashion, nykaa → beauty. **Two of the four allowed merchants are in that table**,
so a large share of owned posts get a category with zero textual evidence — and then
"engagement rate by category" partly measures merchant effect, and the daily plan cites it as
category evidence.

Either drop the hint table, or record the category's SOURCE (text vs merchant-inferred) so the
analytics can separate the two populations and the UI can say which it is. Do not leave it
indistinguishable in the payload.

### [S3-a] `price_band` on a multi-deal post is its cheapest item
`parser.py:242-244` uses `min(stated)`. Correct for a single deal (sale price vs MRP), wrong
for a loot board listing ₹80 and ₹2999 — it lands in `under-299` and skews the leaderboard.
`is_multi_deal` is computed one function away (`normalizer.py:171`) and can gate it.

### [S3-b] `parse_discount_pct` takes only the first cue match
`parser.py:214` uses `.search`. "Flat 10% extra off … 76% OFF" records 10 — systematically low
on boards.

---

## GROUP D — `be/src/services/analytics/views.py`, `be/src/services/analytics/deal_gap.py`

### [S2-f] `segment_performance` is all-time, unlabelled, and top/bottom overlap
`views.py:243-256`. `full = compute(s)` with no start/end — **lifetime** numbers handed to a
DAILY plan whose other facts are windowed, and the returned dict carries no window key. The
product's whole claim is that every number is labelled with its window and sample.

Worse: `bottom_categories = cats[-top_n:] if len(cats) > top_n else []` — with 4 categories,
top = `cats[0:3]` and bottom = `cats[1:4]`, so **two rows are simultaneously "top" and
"bottom"** and both go into the prompt (`planner.py:534-541`) under contradictory labels.

Fix: carry the window, and make top/bottom disjoint.

### [S2-d] Segment analytics have no coverage denominator; only `segments` is gated
`views.py:108-116`, `:165-171`. Rows with NULL category/band are dropped from the buckets and
counted nowhere, so nothing can say "this leaderboard covers 31% of the window's posts" —
which, given how often `infer_category` returns None, is the difference between an honest
number and a confident one. Add a categorized/total pair per dimension to the payload.

Separately `by_category`/`by_discount_band`/`by_price_band` are ungated, so an n=1 bucket at
100% engagement renders as the tallest bar — right next to a card that brags "small sample
sizes never win". Gate them or mark sub-gate buckets in the payload.

### [S2-e] `deal_gap`'s "share of posts" is a share of *categorized* posts, across two
differently-covered populations
`deal_gap.py:29-39`, `:49-64`. `_category_counts` filters `category IS NOT NULL` and the
totals sum only those rows, but the UI labels it "Share of posts per category, us vs tracked
competitors". Owned posts run through 4 known merchants, two of which get a free category from
`_MERCHANT_CATEGORY_HINTS` [S2-c]; competitor posts mostly do not. So owned coverage is
systematically higher, and `gap = comp_share - owned_share` compares differently-sized
populations. `over_indexed_by_competitors` inherits the bias.

Fix: report each side's categorized/total coverage in the payload, or compute shares over all
posts with an explicit uncategorized bucket.

---

## GROUP E — `next/`

### [S1-e] The plan page's schedule column renders blank for every new plan
`next/app/(dashboard)/plan/page.tsx:316-325`; `next/types/api.ts:317`. The table renders
`{s.window_ist}` and `{s.count ?? 1}`. Per-post plans carry **neither** key, so the column
that *is* the feature ("the schedule is real") is blank on every row. `DailySlot` still
declares `window_ist: string` as required — the type is now a false statement about the
payload, and tsc passes only because the response is cast, not validated.

Fix: read `time_ist` with a `window_ist` fallback; mark both optional in `DailySlot`. Show the
per-post merchant/theme/type too — this is the screen where the user judges whether the agent
planned a real mix.

### [S2-d / S2-e — UI half]
Surface the coverage denominators GROUP D adds, and mark or gate sub-sample buckets, so no
screen shows a 1-post bucket as a confident winner.

---

## Also required
- **[S3-c]** Write gate evidence for all three slugs, not just one.
- **[S3-d]** Fix the four tests that assert the implementation rather than the requirement —
  they are the reason S1-a, S1-b and S1-d all shipped green:
  `test_per_post_planning.py:113-117` (`len == 5`), `:152` (`len(set(times)) >= 2` for 8 posts),
  `test_slot_mix_enforcement.py:59-63` (pool vocabulary == stored vocabulary, counts start
  empty), `test_deal_dimensions.py:329` (canned plan uses the LEGACY shape, so the
  deal-dimension AC5 test never exercises the schema that shipped).

## Confirmed clean — do not re-spend time here
`_expand_slots` determinism under the 1-min cron (sort key `(fire, si, sub)`, single-pass
collision push; dedup key unaffected → no double-fire, no never-fire). Legacy `window_ist`
execution and span-spreading. The never-drop-a-slot guarantee. `_pick_fresh` tier semantics for
existing callers. `_reduce`'s `engagement_rate` never None. `migrate.py:_ADDITIONS` complete and
SQLite-compatible for all four columns. Frontend types match the Python payloads key-for-key for
`segments`/`by_*`/`deal_gap`, and those two insufficient-data states are real.
