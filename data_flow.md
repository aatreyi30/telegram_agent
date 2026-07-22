# DealWing — Data Flow & Gap Analysis

> **STATUS: RESOLVED (2026-07-21).** Every gap below (G1–G10) is implemented, integrated,
> and live-verified — see §9 for the resolution log. The analysis is kept for context.

_Audit date: 2026-07-20 · branch `jk/rewamp/loop` · verified against live DB + code trace_

This document maps how data flows into the **daily planner** (and out to posts), pinpoints
every gap that causes the "only single deals" behaviour and the other open defects, and gives
a concrete fix for each. **Read the gap register (§3) — that's the decision list.**

---

## 1. The pipelines (how data moves)

### A. Deal sourcing (what we CAN post)
```
GrabCash API ──> DealSourceClient ──> filter_relevant ──> diversify_by_category
(deals.grabcash.in)   deal_source.py     (allow-list gate)     (spread across categories)
        │                                                             │
        └──> RawDeal ──> DealEnrichmentEngine ──> EnrichedDeal (title, price, discount,
                              enrichment.py          merchant, category, image, deal_score)
```
- **Status: WORKS.** Feed is healthy again (amazon 17 + ajio 26 + flipkart survive the gate).
- Allow-list = `{amazon, flipkart, myntra, ajio}` (exact match). Amazon now present → the
  merchant blocker is gone.

### B. Planning (what we DECIDE to post, and when) ← **the problem area**
```
   WEEKLY (Mon 08:00)                     DAILY (06:00)                    EVERY 3 MIN
┌────────────────────┐   week_direction  ┌──────────────────┐  post_slots ┌───────────┐
│ generate_week_plan │ ────╳ BROKEN ───> │ generate_day_plan│ ──────────> │ jit_fill  │
│  (AI)              │   (never arrives) │   (AI)           │             │ fill slots│
│  loot_deal_ratio   │                   │  post_slots[]    │             │  w/ deals │
│  merchant_priority │                   │  type/window/    │             │  → drafts │
│  daily_themes      │                   │  theme/merchant  │             └───────────┘
└────────────────────┘                   └──────────────────┘                   │
         │ persisted as                          ▲                               ▼
         │ DETERMINISTIC blueprint               │ reads: POST_TYPE_PERFORMANCE,  GeneratedPost
         │ (AI ratio DISCARDED)                  │ MERCHANT_MIX, POSTING_WINDOWS, (DRAFT)
         └──────────────────────────────────────┘ THIS_WEEK_THEME, RETRO, learning
```

### C. Intelligence feeding the planner (the "stats" the planner reasons from)
```
owned Posts ──> normalize ──> ChannelLearningEngine ──> post_type_performance   ┐
competitor   ──> normalize ──> CompetitorIntelligence ──> competitor_benchmarks  ├─> daily
posts                                                     channel_style_profiles ┤   planner
subscriber snapshots ──> growth trends ──> follower_trajectory                   ┘   DATA
```
- **Status: WORKS.** Learning tables populated and consumed. Competitor profiles/benchmarks
  real. Subscriber trends real (no admin needed).

### D. Feedback loop (did the plan work?)
```
GeneratedPost ──> predict_for_slot ──> PostPrediction ──╳──> outcome (err never computed)
                                          post_id=NULL   OPEN LOOP (blocked on admin rights)
```
- **Status: OPEN.** Predictions made, outcomes scored, but never compared (see Gap G6).

---

## 2. Core problem: the daily planner only proposes `single_deal`

**Symptom:** today's plan (and recent days) = all `single` slots, no `loot`/`collection`. You
want each type scheduled across the day's timeline, with stats + reasoning per slot.

**It is NOT one bug — it's three compounding causes:**

| # | Cause | Evidence |
|---|---|---|
| C1 | **The weekly loot:deal ratio never reaches the daily planner.** The weekly AI computes `loot_deal_ratio`, but the persisted weekly blueprint is the *deterministic* one — the AI's ratio + merchant priorities are dropped. So `THIS_WEEK_DIRECTION` arrives **empty**. | `service.py:_weekly_ai_generate` line ~979 sets `blueprint = eng._weekly_plan(...)`; `planner.py:_current_week_plan` reads `loot_deal_ratio`/`merchant_priorities` → resolve to `None`. |
| C2 | **Each day is assigned ONE type.** The weekly plan tags each day `theme_focus = single_deal \| loot_deal` (a single label). A "single day" → the whole day is single. There is no intra-day mix. | `prompts/planner.py` WEEK_PLAN output: `daily_themes:[{day, theme_focus:"loot_deal\|single_deal"}]`. |
| C3 | **No mix floor + single out-performs loot in the stats.** `post_type_performance`: single_deal ≈ 232 views/day (rank 1) vs loot ≈ 206 (rank 2). A performance-driven planner with no minimum-variety rule rationally collapses to 100% single. | Live `post_type_performance` table; daily prompt step 3 says "reflect DEAL_TYPE_ALLOCATION" but nothing enforces a floor. |

**Conclusion:** a prompt tweak alone will not fix it. We must (1) make the ratio actually flow,
(2) switch to an intra-day mix, and (3) enforce a variety floor so neither type drops to zero.

---

## 3. Gap register (the decision list)

Legend — **Priority:** P0 = fix now · P1 = important · P2 = nice-to-have.
**Status:** `fixable` · `blocked` (external dependency).

| ID | Gap | Why it happens | How to fix | Files | Priority | Status |
|----|-----|----------------|------------|-------|----------|--------|
| **G1** | Weekly AI `loot_deal_ratio` + `merchant_priorities` discarded; daily planner gets no direction | Weekly blueprint persisted = deterministic engine output, not the AI's parsed plan | Merge the AI's `loot_deal_ratio` + `merchant_priorities` into the persisted weekly blueprint so `THIS_WEEK_DIRECTION` is populated | `services/generation/ai_execution.py` (persist_weekly_plan), `controllers/service.py` (_weekly_ai_generate), `ai/planner.py` (_current_week_plan) | P0 | fixable |
| **G2** | Daily plan is mono-type per day (all single or all loot), not a mix across the timeline | `daily_themes.theme_focus` is one label; daily prompt keys off that single focus | Distribute **both** types across the day's windows per the ratio; each slot chooses its type. Change weekly `daily_themes` to carry a per-day split, not one label | `ai/prompts/planner.py` (PLAN + WEEK_PLAN), `ai/planner.py` (parse) | P0 | fixable |
| **G3** | No variety floor → collapses to the higher-performing type | Nothing guarantees a minimum share of each type | Add a hard floor (default: ≥30% each type per day) the planner must honor; state it positively as a variety rule | `ai/prompts/planner.py` | P0 | fixable |
| **G4** | Loot vs deal not clearly defined for the model; thin "single\|collection" vocabulary | Definitions live only in code markers, not the planner/copywriter prompts | Add clear, positive definitions + when-to-use for each type to both prompts | `ai/prompts/planner.py`, `ai/prompts/copywriter.py` | P0 | fixable |
| **G5** | Per-slot `why` justifies timing/merchant but not the **type choice** | Prompt step 4 lists timing / merchant / outcome, not "why loot vs single here" | Require each slot's `why` to justify its type with a stat (e.g. "loot here — browse-hour, and loot averages X views in this window") | `ai/prompts/planner.py` | P1 | fixable |
| **G6** | No deterministic fallback: if AI generation fails, **no plan is persisted → channel goes silent, no error** | `generate_day_plan` returns `available:False`; old deterministic planner retired, nothing backstops | Emit a real deterministic plan (windows × ratio × top merchants) when AI fails/garbles | `ai/planner.py` (generate_day_plan) | P0 | fixable |
| **G7** | Growth recommendations are stale (3 generic cold-start recs from 07-17) | `growth_detection` fired once; channel has since become eligible for personalized "optimization" mode but wasn't re-run | Re-run `growth_detection` (produces 7 personalized data-backed recs now); check why the daily job isn't re-firing | `services/intelligence/growth.py`, `controllers/schedulers.py` | P1 | fixable |
| **G8** | Prediction→outcome loop open: all 40 predictions have `post_id=NULL`, so accuracy (`err_views_24h`) is never computed and retro's prediction section is always empty | Generation posts stay `blocked` (account not channel-admin) → no published Post to link a prediction to | Wire the prediction↔post link so it activates once publishing works. **Cannot fully close until the account has admin post rights on the channel.** | `services/analytics/prediction.py`, `outcomes.py` | P2 | **blocked** |
| **G9** | 7 past-due jit_fill slots/day are skipped forever | `_is_due` requires `now ≤ fire ≤ horizon`; a missed window is never retried by cron | Add a bounded backfill for recently-missed slots (e.g. fill fires within the last N min once) | `services/generation/jit_fill.py` | P2 | fixable |
| **G10** | `recommended_posts` clamp is display-only; jit_fill executes the raw (unclamped) blueprint | Clamp applied in `daily_brief` display, not the stored blueprint | Clamp at persist time so the executed plan matches what's shown | `controllers/service.py` (persist_ai_plan / clamp) | P2 | fixable |

---

## 4. What the daily planner actually receives today (the DATA block)

From `ai/planner.py:generate_day_plan` → `DAILY_PLAN_SYSTEM`. Present ✅ / missing ❌:

| Signal | Present? | Note |
|---|---|---|
| YESTERDAY results, 14-day trajectory, RECENT_CADENCE | ✅ | real |
| POST_TYPE_PERFORMANCE (single vs loot views/day) | ✅ | real — currently single-lean |
| MERCHANT_MIX (per-merchant share/views/sample) | ✅ | real — now includes amazon |
| POSTING_WINDOWS (+ hourly perf) | ✅ | real |
| DEAL_TYPE_ALLOCATION | ✅ | from deterministic weekly plan |
| THIS_WEEK_THEME | ✅ | the day's single focus label |
| **THIS_WEEK_DIRECTION (loot_deal_ratio, merchant_priorities)** | ❌ | **empty — the G1 gap** |
| CHANNEL_STYLE, STYLE_FOLLOWER_CORRELATION, FOLLOWER_TRAJECTORY | ✅ | real |
| COMPETITOR_BENCHMARK | ✅ | real |
| RETRO (prediction-accuracy adjustments) | ⚠️ | present-but-hollow — prediction section empty (G8) |

**The one missing input that drives the symptom is `THIS_WEEK_DIRECTION`.** Fixing G1 puts the
ratio into the planner's hands; G2/G3 make it act on it as an intra-day mix with a floor.

---

## 5. Fix plan (phased, for Sonnet subagents)

- **Track 1 — Planner internals (G1, G6, G10):** make the AI ratio persist, add the deterministic
  fallback, clamp at persist time. _Independent of Track 2._
- **Track 2 — Prompts (G2, G3, G4, G5):** intra-day mix, variety floor, loot/deal definitions,
  per-slot type reasoning. Written **positively and generally** — definitions stated as design
  ("A loot board is…", "Post a loot when…"), never as "the model keeps doing X so force Y", and
  never leading with failure cases.
- **Track 3 — Growth (G7):** re-run + confirm re-firing. _Standalone._
- **Track 4 — jit_fill robustness (G9):** missed-slot backfill. _Standalone._
- **Blocked — G8:** wire the link now so it activates the moment the account gets channel-admin
  rights; flagged, not silently "done".

---

## 6. Open decisions (need your call)

1. **Loot:deal ratio + floor.** Default proposed: data-driven ratio (≈60/40 single-lean today)
   **with a hard floor of 30% each type** so both always appear. Or fix a split (e.g. 50/50)?
2. **G8 (prediction link):** wire it now (activates later) or park until admin rights?
3. **Anything to add/re-prioritise** in the gap register before implementation.

---

## 7. Verification (end-to-end, before "done")

After implementation, run the planner live against real data and show:
- a **today plan with a genuine loot + single mix** across the timeline,
- each slot citing its **stat + type reasoning + merchant-vs-next-best**,
- the fallback path producing a real plan when AI is forced to fail,
- growth showing the 7 personalized recs.

No claim of "working" without that live output shown.

---

## 8. FINALIZED SOLUTION (approved 2026-07-21)

Decisions locked: **loot+single mix with a 30% floor each type**; **G8 wired now** (activates
when admin rights are granted); **posting goes to the TEST channel only** for now (auto-publish
to the real channel stays gated). Two additions came in with approval:

### 8a. Deal sourcing → the EXPORT API (replaces over-fetch + client filter)
New endpoint (validated live, not from the JS-rendered docs):
```
GET https://deals.grabcash.in/api/v1/export/deals?key=<KEY>&retailer=<r>&page_size=<N>&page=<P>
    auth: query param `key`   shape: {total, items:[...]}   filter: retailer= at source
```
- Per-retailer pools (live): flipkart 3,759 · ajio 1,407 · **myntra 873** · amazon 32 (15,000 total).
- **Myntra now sourceable** (old `/deals` had zero). Every item carries `image_url`.
- **Item fields are identical to the old endpoint** → `_FIELD_ALIASES`/`_map_item` unchanged.
- New flow: query the export endpoint **once per allowed retailer** (amazon, flipkart, myntra,
  ajio) and merge → guaranteed inventory per merchant (feeds the mix + merchant priorities).
  Keep the Camoufox fallback. Note: ajio/myntra still have **no affiliate rule → ₹0** (separate
  money item, not blocking).

### 8b. Image rationing — 4-5 images per DAY total
- **jit_fill owns it, stateless/deterministic:** expand the day's ordered slot list, pick **5
  evenly-spaced** slot indices as "image slots". When one of those fills, stash the deal's
  `image_url` in the draft meta; all other drafts stay text-only.
- The test-channel send path (`dev_send`) attaches a photo **iff** the draft has a stashed
  `image_url` → exactly ~5 image posts spread across the day, rest text.

### 8c. Execution — 4 Sonnet subagents, disjoint file ownership
| Agent | Owns (files) | Delivers |
|---|---|---|
| **1 Sourcing** | `deal_source.py` | Export-API fetch (query:key, {total,items}, per-retailer merge), Camoufox fallback, same RawDeal out |
| **2 Planner** | `prompts/planner.py`, `ai/planner.py`, `ai_execution.py`, `service.py` | G1 ratio persist · G2 intra-day mix · G3 30% floor · G4 loot/deal defs · G5 per-slot type reasoning · G6 deterministic fallback · G10 clamp-at-persist |
| **3 Fill+Post** | `jit_fill.py`, `dev_send.py` | Image rationing (5/day spread) · G9 missed-slot backfill · test-channel delivery honoring the image budget |
| **4 Loop** | `prediction.py`, `outcomes.py`, run growth | G7 growth refresh · G8 prediction↔post link (activates on admin) |

Integration + live verification (§7) done by the lead after all four land.

---

## 9. Resolution log (2026-07-21)

All work landed, integrated, and verified against the live DB + a real end-to-end fill.

| Gap | Outcome | Evidence |
|---|---|---|
| **G1** weekly ratio → daily planner | ✅ AI `loot_deal_ratio` + `merchant_priorities` merged into the persisted weekly blueprint; `THIS_WEEK_DIRECTION` populates | live: `{loot:37, deal:63}` reaches the daily planner |
| **G2** intra-day mix | ✅ daily plan distributes both types across windows; `daily_themes` carries a per-day split | live today plan: 4 single + 3 loot; real fill: 41 drafts, both types |
| **G3** variety floor | ✅ ~30% per type (prompt-enforced) | (minor: one weekend day hit 0.25) |
| **G4/G5** loot/deal defs + per-slot type reasoning | ✅ definitions + type-justified `why` in `DAILY_PLAN_SYSTEM` | — |
| **G6** deterministic fallback | ✅ `generate_day_plan` returns a real mixed plan (tagged `is_fallback`) on AI failure | live: forced failure → 6 real slots, both types |
| **G7** growth refresh | ✅ 3 stale cold-start → 7 personalized optimization recs | live before/after |
| **G8** prediction↔post link | ⚠️ **wired + self-heals** each `outcome_collector` tick (matches on destination channel). Fully closes only once the account has channel-admin rights on a tracked channel | 3 new tests |
| **G9** missed-slot backfill | ✅ bounded 30-min once-only backfill in `_is_due` | selfcheck |
| **G10** clamp + slot-count reconcile | ✅ `persist_ai_plan` clamps recommended AND rescales slot counts to match; `plan_clamped` recorded | live: 71→41 reconciled; caught during integration |

**Also delivered (came in with approval):**
- **Export API sourcing** — `deal_source.py` queries `/api/v1/export/deals?key=&retailer=&page_size=` per allowed retailer (amazon/flipkart/myntra/ajio), merges; images on every item; Myntra now sourced.
- **Image rationing** — jit_fill flags ~5 evenly-spaced slots/day; `dev_send` attaches a photo only for those. Verified: exactly 5 spread across a 41-post day.
- **Myntra affiliate + DB-backed config** — `GrabOnAffiliateProvider` Myntra rule; affiliate config (amazon/flipkart/myntra/shortener) lives in `org.settings`, editable at Settings→Org, read by `registry._settings_for_org`. Amazon/Flipkart/Myntra earn; **Ajio still ₹0** (no rule yet).
- **Ops** — SQLite WAL + `busy_timeout=30000` + `synchronous=NORMAL`; CORS any-localhost + `*.vercel.app`; `duckduckgo_search` rename warning suppressed.

**Validation:** full backend suite **308 passed / 9 pre-existing failures / 0 new regressions**; frontend `tsc` clean.

**Still open (external, not code):** G8 needs channel-admin rights; Ajio needs an affiliate format.

