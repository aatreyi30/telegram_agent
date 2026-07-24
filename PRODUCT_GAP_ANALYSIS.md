# Product Gap Analysis — DealWing / GrabOn Telegram Growth Agent
### End-to-end evaluation, verified against live code + `be/data/tgagent.db`

**How this was produced:** every subsystem block (ingestion, enrichment, planning, generation/publish, analytics, prediction, learning/reasoning, scheduler, DB schema, org, frontend, API) was read at source level and cross-checked against the live SQLite DB — row counts, `scheduler_runs` history, and real sample rows. Where an earlier draft or the team's own docs (`data_flow.md`, `pre-deployment.md`) made a claim, it was independently verified and, in several cases, **corrected**. File:line references and query results are inline.

---

## 0. The one-paragraph truth

**This is not a dumb product with lazy prompts. It's a genuinely well-engineered reasoning layer sitting on top of a broken execution-and-operations stack, so almost none of its intelligence reaches the channel or the screen.** The planning prompts, competitor intelligence, prediction model, and retro/learning design are all more sophisticated than the visible output suggests. The reason daily/weekly plans feel "vague, one-category, not up to the mark" is a stack of four separable failures, none of which is "the AI is bad":

1. **Operational — the brain is frozen at July 15.** The daily/weekly cron jobs that generate plans, reports, retros, and learning have **fired once (or never)** because APScheduler cron triggers only fire if the process is alive at an exact IST minute, and this deployment isn't. The posting loop (interval-triggered) keeps running off a **stale plan generated on 2026-07-15**.
2. **Execution reliability — a third of posts are silently blocked, and 40% of the rest drift off-plan.** A timeout-as-dead-deal bug blocks 37% of posts permanently; a fill-time "broaden to any" fallback discards the planner's category/merchant intent on ~40% of posts; a two-writer race silently keeps the *deterministic* (dumber) weekly blueprint over the AI one.
3. **Data/permission ceiling — the feedback loop can't close.** The tracked channel has `can_view_stats=0` and the account isn't admin, so view-source, join-source, and forward data never arrive, prediction-accuracy has **never computed once**, and — separately — no click/CTR/revenue data exists anywhere (the affiliate network exposes none).
4. **Reporting/UI — the good data that *does* exist is mislabeled or hidden.** "CTA rate" is not click-through, "best category" is actually a single post's merchant, the fully-built weekly-retro panel renders blank, and rich competitor style-metrics are dropped at render.

Fixing #1 and #2 is mostly operational + small code changes and would transform the visible output almost immediately. #3 is the real strategic ceiling and the thing that actually blocks selling this as a monetization engine. #4 is renames and re-plumbing of data that already exists.

**But the deeper product question — "even when a plan renders, why is it hollow and only Telegram stats, and what real data can replace that?" — is answered in §0.5, which is the section to read first if the goal is making the product *useful*, not just *reliable*.**

---

## 0.5 THE CORE PRODUCT GAP — why the demo showed "nothing useful," and the path to real data

> This section is the answer to the real question: *forget the frozen jobs and permissions — even when a plan DOES render, why is it hollow, and what genuinely useful data can we ship instead?* Every number below is from the live DB (2026-07-23).

### What the plans literally contain today (the hollowness, proven)

**Weekly plan is empty by construction.** The entire stored weekly blueprint (`campaign_plans` id 7) is:
```
posts_per_day: 34 · alternate single-deal / loot day-by-day
deal_type_allocation: single=150 posts@232 views, loot=88@206 views
posting_windows: []   upcoming_events: []
```
There is nothing else computed, so the `/plan` week screen has nothing else to show. The only substance is the AI *digest* paragraph, and it knows exactly three things: follower gain, single-vs-loot view average, and "these merchants are missing." No per-category / per-brand / per-price targets, no engagement goals, no time windows. **The screen shows nothing useful because nothing useful is computed.**

**Daily plan looks detailed but recites one number.** Every one of the 8 slot rationales in the latest daily plan (id 10) cites the *same* figure — `avg_views_per_day of 206.1` — for fashion, electronics, beauty, health alike. It even prints "Expect around **4.1 views**" (a broken per-slot prediction). `max_price`/`min_price` are always `null` — the price dimension is never used. The "reasoning" is theatre over a single channel-average view count.

### The three flaws that make it useless (all fixable without permissions/clicks/admin)

**FLAW A — The only outcome signal it uses is channel-average VIEWS.** It captures **reactions on 294/375 owned posts (78%)** and **9,639/11,214 snapshots** and throws them away entirely. Forwards are effectively dead (15/375, max=1 — the channel doesn't expose them). So of two usable engagement signals it optimizes the shallower one (views = reach = subscriber count + algorithm) and ignores the better one (reactions = whether the deal actually *resonated* — the real traction proxy for a deal channel). **Using reactions/views as an engagement RATE is buildable today and needs no new data.**

**FLAW B — Performance is never attributed to any deal dimension, because category/price never lands on a measured post.** Owned posts (`normalized_posts`) already carry, extracted from the post text: `primary_merchant_key` (7,848/7,975), `price_threshold` (1,201), `is_multi_deal` (1,836), `has_coupon` (199). But they carry **no category and no discount-band**. The category (`electronics-and-gadgets`, `fashion-and-lifestyle`) lives only in `enriched_deals`/the plan side and is discarded before it touches a post whose views we measure. So the engine is *structurally incapable* of saying "electronics beats fashion" or "70%+ off beats 40%." Everything collapses to merchant + views. **Fix: extend the existing text-extraction pipeline (the one that already pulls merchant + price-band) to also emit category + discount-band — no permissions, no new source.**

**FLAW C — a hard architectural fact that shapes the fix: the channel we can measure is not the channel the engine posts to.** The 375 posts with real views/reactions are `GrabOnIndiaOfficial`'s own **scraped historical** posts (id range 1–375) — they have **no `deal_ids`, no category link**. The engine's own generated posts (which *do* carry deal metadata + category via `format_meta.slot.theme`) went to `@demotestchanneljk` (68 posts) which has ~no audience. So you cannot answer "which category gets traction" by joining the engine's generated deals to the engine's engagement — that data is split across two channels. **This is why attribution must come from extracting dimensions out of the real channel's post text/links (Flaw B's fix), not from the generation metadata.** It's an attribution-architecture fact, not a permissions problem.

**FLAW D — competitor intelligence is style-only, not deal-level.** `competitor_profiles` stores emoji-rate, CTA-rate, coupon-rate, posts-per-day; `post_classifications` is a style KMeans cluster; `competitor_benchmarks` is per-style-dimension deltas. There is **no per-category / per-brand / per-price breakdown of what competitors post and win with.** So the system can never produce the single most valuable output for a deal channel: *"rivals ride electronics-under-₹500 and boAt/Titan; you're absent — post it."* The raw material exists (7,600 competitor posts with full text), it's just never extracted at the deal level.

### The bottom line on usefulness

You have a rich deals feed (category, brand, price, MRP, discount%, deal-score) and 7,600 competitor posts flowing **in**, and the product analyzes *none* of it — it only mirrors Telegram views back out. That is the entire "nothing beyond Telegram data" complaint, and it is an analytics-and-plumbing gap, **not** a data-availability gap. With views (100%) + reactions (78%) + deal dimensions (all present) we can ship real intelligence with zero new permissions.

### Build plan — "everything," phased so each phase is demoable

**Phase 1 — Deal-dimension attribution + engagement-rate analytics (the keystone; unblocks all others).**
- Extend the owned-post text/link extraction to emit `category` and `discount_band` alongside the merchant/price-band it already produces; backfill the 375 posts.
- Add engagement **rate** (reactions ÷ views) as a first-class metric next to raw views.
- Ship performance leaderboards by **category / brand / price-band / discount-band / hour**, ranked by engagement rate — e.g. "beauty under ₹999 = your top segment," "70%+ off = 2× reaction rate," "electronics peaks 18:00–23:00."
- *Result:* the first screens in the product that are NOT reworded Telegram vanity stats.

**Phase 2 — Competitor deal-gap intelligence.**
- Run the same deal-dimension extraction over the 7,600 competitor posts (category/brand/price from their text).
- Compute you-vs-rivals coverage + engagement gaps per category/brand → "they win with X, you're absent."
- Surface the already-computed-but-hidden competitor CTA/coupon/similarity tiles at the same time (§5.4).

**Phase 3 — Rewrite the plan generation to consume Phases 1–2.**
- Replace the thin weekly blueprint with concrete per-category/brand/price bets + engagement targets + real time windows; feed the daily prompt the measured dimension numbers so slot rationales cite *specific* evidence, not "~206 views/day."
- Kill the broken "4.1 views" per-slot number; use the dimension-level rate instead.

**Phase 4 — Surface it all in `/plan` and analytics UI**, and (only if monetization is the goal) add the internal `/r/{id}` click redirect to layer real CTR/revenue on top (§4.3) — the one piece that does need a build beyond analytics.

Phases 1–3 are what turn this from a Telegram mirror into a deal-intelligence engine, and none of them need admin rights, click data, or the frozen jobs fixed first (though fixing those makes the numbers fresher). Detailed per-flaw fixes and file targets are in §5 and §8 below.

---

## 1. What is genuinely good (don't rebuild these)

- **The planning prompts are rigorous and honest.** `daily_plan.py`/`weekly_plan.py` force per-slot reasoning to cite real numbers, ban vague phrases without a backing stat, require naming the passed-over runner-up merchant, and explicitly flag their own ceiling: *"Views are the proxy you can measure per slot; keep that honest."* This is not the weak point.
- **Telegram engagement capture is real and deep** — `post_metric_snapshots`: **10,840 rows**; views/forwards/reactions per post via Telethon. Solid.
- **Competitor intelligence is a real moat** — `competitor_posts`: **7,587 rows**, `competitor_benchmarks`: **100 rows**, 9–10 profiles with posting cadence, style rates, deal-mix, similarity-to-owned. Most single-channel operators have nothing like it.
- **A second, better deal-ranking engine already exists** — `DealRanker`/`DealSelector`/`StrategyAwareSelector` (`ranking.py`) with a learned score and five diversity buckets (loot/trending/budget/high-value/exploration). It's fully built. (It's just not wired to the scheduled path — see §3.4.)
- **The prediction model is honest, not fake** — a real median-lookup with a 4-level fallback, correctly labeled `baseline_v1`, correctly collapsing to `channel_median` because volume is too low to do more.
- **The reflective-loop code is built and correct** — retro writer, reasoning engine (it *does* persist: `reasoning.py:92-98` `s.add(ReasonedInsight)` inside `session_scope()`), learning writers all work when invoked. They're starved, not missing.
- **Subscriber growth is real** — 26,506 → 28,437 in 13 days (+1,931). Top-of-funnel motion works.
- **Idempotency/dedup is solid** — 0 double-posted deals, 0 double-fired slots, clean retry/reclaim state machine (`scheduler.py:71-173`).

**Corrections to the earlier draft, on the record:** `post_outcomes` is **not** empty (375 rows). `ReasoningEngine` does **not** compute-and-discard (it persists). The exact-match merchant gate is **not** the current live root cause (fixed on the primary path 07-20). The "growth off-by-one" bug **does not exist** in `growth.py` (that query is inclusive and correct). Don't act on those.

---

## 2. LAYER 1 — Operational: the intelligence layer is frozen (P0, root cause of "no fresh insight")

**Evidence — `scheduler_runs` (5,690 rows of real fire history):**

| Job (trigger) | All-time runs | Last run | State |
|---|---|---|---|
| jit_fill / queue_processor / normalize / telegram_sync … (interval) | 300–1,490 each | 2026-07-23 | ✅ fire constantly |
| **daily_plan** (daily 06:00) | **1** | **2026-07-15 04:08** | ⛔ frozen |
| **daily_report** (daily 05:15) | **1** | **2026-07-15 04:08** | ⛔ frozen |
| **learning** (daily 02:00) | **1** | **2026-07-15 04:08** | ⛔ frozen |
| **growth_detection** (daily 05:30) | **1** | **2026-07-15 04:08** | ⛔ frozen |
| **weekly_retro** (Mon 07:30) | **0** | never | ⛔ never fired |
| weekly_report / monthly_report / competitor_intel / competitor_discover / url_health / db_cleanup | **0** | never | ⛔ never fired |

All four daily jobs ran **once, at the identical second `07-15 04:08`** — an APScheduler boot catch-up (`coalesce=True`, no `misfire_grace_time`), not a real cron fire. After that, `next_run_time` moved to the next day's IST slot and the process was never alive at 02:00–07:00 IST again. Weekly/monthly jobs had a future next-run at that boot, so got no catch-up and have **literally never run**.

**Consequences, all verified:**
- `campaign_plans` (the daily/weekly plan store) last meaningfully generated on skip-day dates (07-14/15/17/20/21/23) — the fingerprint of sporadic *manual* triggers, not a daily cadence. **`jit_fill` is posting today's slots off a plan whose brain last thought on July 15.**
- `daily_channel_reports` frozen at **2026-07-17**.
- `weekly_retros`, `reasoned_insights`, and most of the "empty tables" in every prior analysis are **this one bug**, not missing code.

**Fix (no business-logic changes):** run the scheduler as a persistent process, OR drive the cron keys from an external scheduler (Render/Railway cron, or GitHub Action hitting a `run-scheduler <key>` endpoint), OR add a startup catch-up that fires any missed daily/weekly job. Add `misfire_grace_time`. This single change un-freezes daily_plan, daily_report, learning, growth_detection, weekly_retro, and repopulates `growth_strategies`/`post_type_performance`/`learning_records` on cadence. **Highest leverage item in the entire report.**

Two jobs won't self-heal even after this:
- **`reasoned_insights`** — `ReasoningEngine` is **not in the JOBS registry at all** (only reachable via the manual pipeline button, `jobs.py:110`). Add a `reasoning` job. It *also* has a volume gate `MIN_PERIOD_POSTS=30` per 7-day window (`reasoning.py:34`) that 117 posts over sporadic days can't satisfy — relax the threshold or widen the window for current volume.
- **`merchant_products` / `product_price_snapshots`** — their collector (`merchant.py`, the boAt/Reliance price-verifier) is **not registered as a job** either. Register it only if that data is actually wanted.

---

## 3. LAYER 2 — Execution reliability: what the owner actually sees as "not up to the mark" (P0)

### 3.1 — 37% of posts are silently BLOCKED by a timeout-as-dead-deal bug
**Evidence:** 44/117 posts are BLOCKED; 43 of the 44 share one reason: `blocked_stale: unreachable (ReadTimeout)`. `publishing.py:88-95` revalidates every deal before send; for BLOCKED/unknown merchants (ajio, nykaa, croma…) the only check is `_http_ok` — a HEAD/GET with an **8-second timeout from a datacenter IP** (`revalidate.py:52-63`). Datacenter IPs get bot-walled by these retailers, the request times out, the post is marked stale → **permanent, never retried** (`_PERMANENT_STATUSES`, `scheduler.py:145-150`).

The code *already knows* this pattern — `_BLOCKED_NOT_BROKEN = (403, 405, 429)` deliberately treats bot-wall HTTP codes as "blocked, not broken." **Timeouts just aren't in that set**, even though a datacenter ReadTimeout to ajio is the identical situation. **Fix: add `ReadTimeout`/`ConnectTimeout` to `_BLOCKED_NOT_BROKEN`** (≈1 line) → unblocks ~37% of the channel's posts. Optionally raise the 8s timeout and add one retry.

**And the operator alert points the wrong way:** `schedulers.py:308-309` reports these as *"N posts blocked (need admin rights)"* — but 43/44 are revalidation timeouts, not rights. Anyone debugging checks admin rights, finds nothing, and never sees the real cause. Fix the alert to read the actual `publish_note` prefix.

### 3.2 — ~40% of posts that DO go out ignore the plan
**Evidence:** among single-deal slots, fill-tier distribution is `exact 40 · theme 10 · any 33` — **33/83 (~40%) matched neither the planned theme nor merchant.** `jit_fill._pick_fresh` broadens to "any fresh unused deal" when the day's scraped pool is thin (`jit_fill.py:140-157`), silently discarding the planner's diversity intent. This is the concrete mechanism behind "posts don't respect the plan" — an executor fallback, not planner stupidity. Fix: when broadening, prefer an under-represented category/merchant for the day rather than pure freshness; alert when a slot can't be filled on-theme.

### 3.3 — The weekly AI blueprint is silently replaced by the dumber deterministic one
**Evidence:** both persisted AI weeklies (`campaign_plans` id 3, 7) store the AI *narrative* (`ai_digest`) but **not** the AI's structured `loot_deal_ratio` / `merchant_priorities` / per-day `loot_share`. The G1 merge that copies those in exists in **only one of two write paths** — the on-demand dashboard path (`service.py:1018-1031`). The **scheduled** `j_weekly_report` runs the deterministic engine, then calls `persist_weekly_plan(..., is_ai_generated=True)`, which hits the unique constraint `(campaign_version, plan_type, target_date, is_ai_generated)` (`models_campaign.py:74`), catches `IntegrityError`, and **returns the existing deterministic row without applying the AI blueprint** (`ai_execution.py:139-159`). So at runtime `_current_week_plan` hands the daily planner `loot_deal_ratio=None, merchant_priorities=None`. This is the `data_flow.md` "C1/C2 fixed 07-21" claim — **still broken in live data** on the scheduled path. Fix: make `persist_weekly_plan` UPDATE-on-conflict, and route both write paths through the same G1 merge.

### 3.4 — The 30% mix floor is prompt-only and violated live
**Evidence:** the floor is a *prompt instruction*; the only runtime guard on the LLM path is `_check_type_mix` which **just logs a warning** (`planner.py:48-60`). Hard enforcement exists only in the deterministic fallback. Live: daily plans 07-17 and 07-20 shipped **100% single** (3/3 slots each) with nothing catching it. Fix: make the floor a hard post-generation repair, not a log line.

### 3.5 — The good ranking engine is wired to a button, not the schedule
**Evidence:** `DealRanker`/five-bucket `DealSelector` are used only in `LiveDealGenerationEngine` (`engine.py`), invoked only from `cli.py` and the manual "Generate Live" dashboard job (`jobs.py:136-152`). The scheduled path (`generate_day_plan` → `jit_fill`) instead reads `ctx.available_deals()` = **top-15-by-discount, "No scoring"** (`context.py:265-278`) with zero merchant/category balancing. So on any day one merchant holds the deepest discounts, the planner's visible pool skews to it regardless of feed health. Fix: apply the existing `diversify_by_category`/per-merchant cap to `available_deals()`, or wire `DealRanker` into the scheduled path.

### 3.6 — The merchant allocator is pure exploitation, no exploration
`_merchant_allocation` = `0.5·recent_share + 0.5·(avg_views/median_views)` (`campaign.py:230-290`). Recency + past-views only — no exploration/UCB term, no clicks, no revenue. Sparse (hour × merchant × type) cells never get deliberately tested, so the system can never *learn* whether an untried combination is better. Fix: add an exploration term that occasionally schedules under-sampled cells.

### 3.7 — Reliability items to also close (from `pre-deployment.md`, verified)
- **No-plan-day = silent zero posts.** Per-post copy has a template fallback (safe), but if the daily *plan* AI call fails there's no `CampaignPlan` → `jit_fill` returns "no AI daily plan" → **zero posts all day, surfaced in-app only** (`schedulers.py:313` admits "no push channel configured"). Add a real alert channel.
- **One bad line can block a whole loot board at publish** — assembly degrades gracefully (needs ≥2 valid), but `revalidate_deals` returns on the *first* failing line and blocks the whole post (`revalidate.py:145-150`). Compounds 3.1 10× on loot posts. Fix: drop the failing line, keep the board if ≥2 survive.
- **Link-less post can publish** — loot lines render `link or ""` (`formatting.py:344`); a failed link-finalize yields a clickable-less "Category - " line. Guard it.
- **`notification_engine` alerts fire into the void** — reports "44 blocked / 7 failures" every 5 min with no push channel for days.

---

## 4. LAYER 3 — Data & permission ceiling: why the loop can't close and can't monetize (P0 strategically)

This is the layer no amount of scheduler/executor fixing reaches — the real cap on the product.

### 4.1 — The tracked channel can't be measured
**Evidence:** the owned channel row (`channels`, `GrabOnIndiaOfficial`) has `can_view_stats=0`, `stats_synced_at=NULL`. `telegram_owned._collect_broadcast_stats` opens with `if not ch.can_view_stats: return` (`:323`). So:
- `daily_view_sources` / `daily_join_sources` = **0 rows, structurally unpopulatable** — you cannot know *where* views or joins come from.
- `post_outcomes` (375 rows) is mostly hollow: `views_24h>0` on only **81/375**, `forwards_24h>0` on only **3/375**, `reactions_24h>0` on **60/375**. `stats_refresh`'s own log says it: *"views refreshed (reactions/forwards need admin/bot)."*
- **`err_views_24h` = 0/375** and `post_predictions.post_id` linked = 0/114 — **the predicted-vs-actual accuracy loop has never closed once.** `backfill_post_links` has never succeeded. So the prediction model can never improve, and "did our forecast hold" is unanswerable.

Also flag the **split-brain**: posts go to `@demotestchanneljk` (test) but analytics track `GrabOnIndiaOfficial` (where stats are off). The loop is measuring a channel it can't get stats from. Decide which channel is the source of truth and get admin/stats rights on it.

### 4.2 — Prediction is channel-median 90% of the time, by design at this volume
`post_predictions.features`: `channel_median 103 · hour_day 11 · hour_day_cluster 0 · hour_day_cluster_merchant 0`. **Zero predictions ever reach merchant or post-type granularity**, and `post_type_cluster` is always `None` at predict time (`prediction.py:329`) so the finer levels are structurally unreachable. At 375 lifetime posts a per-(3h × weekday × cluster × merchant) cell never hits `MIN_SAMPLES=5`. "Which time/merchant is best" is **unanswerable at current volume** — needs either much more volume, a collapsed feature space (category + 4h buckets), or deliberate exploration (§3.6).

### 4.3 — No click / CTR / conversion / revenue data anywhere
`affiliate_links` = **0 rows** (the model exists with a `clicks` column). No UTM injection, no redirect/shortlink the app controls, no click webhook. The affiliate network (GrabOn) exposes no click API — the code honestly documents this (`models.py:421-439`, *"clicks stays NULL unless an operator manually supplies portal data — we never estimate it"*). **This is the single gap that most blocks selling this as a monetization engine** — nobody can answer "which category/merchant/post made money," only "which got views."
**Fix (buildable without the network's cooperation):** route every outbound link through an **internal redirect** `/r/{link_id}` → 302, logging the click server-side first. `AffiliateLink` already has `clicks`/`short_url`/`resolved_url` — schema's ready. This one build unlocks real CTR per post/merchant/category and turns "CTA rate" into a true metric.

### 4.4 — No revenue / LTV / cohort / retention
`daily_subscriber_stats` tracks net joins/leaves (good) but there's no cohort table (which join-cohort *retains*, which post types produce subscribers who stay/buy) and no revenue to tie it to. For a "sellable product" pitch, "what's the payback per subscriber" is currently unanswerable.

---

## 5. LAYER 4 — Reporting & UI: good data mislabeled or hidden (P1, mostly renames/re-plumbing)

### 5.1 — "Category" analytics is secretly merchant analytics — and it's lost at the schema, not the report
`enriched_deals.category` is **229/229 populated, 0 null**, clean taxonomy (fashion-and-lifestyle, electronics-and-gadgets, beauty-and-personal-care…). But `NormalizedPost` — the table the owned-post analytics path reads — **has no category column at all** (`PRAGMA table_info` confirms only `primary_merchant_key`). So `daily_report.py` computes `Counter(merchant)` and stores it into a column literally named `category_mix`; `best_category`/`worst_category` are the **merchant of the single top/bottom-viewed post** (live proof, 07-17 owned report: `category_mix:{"ajio":1}, best_category:"ajio"`). **Fix requires a generation-time schema change** — add `category` to `NormalizedPost`, carried from `EnrichedDeal` — a report-layer tweak alone can't recover it because category never reaches `normalized_posts`. (The *forward-looking* slot table already shows true category correctly — so the plumbing is half there.)

### 5.2 — "CTA rate" is a manual text-count, NOT click-through — and as a performance metric it is useless
**What it actually is:** during normalization we parse each post's text and flag whether it contains a call-to-action phrase (`normalized_posts.cta_texts`). Then `analytics/page.tsx` renders `cta_rate = (posts whose text contains a CTA) / total posts × 100` (`views.py:84,182`). **It is a self-referential count of our own output** — "how many of our posts have a CTA written in them." It has nothing to do with anyone clicking.

**Where the data comes from:** Telegram gives **views, forwards, reactions only** — never clicks or CTA taps. So "CTA rate" is not "from Telegram" in any outcome sense; it's our own regex over post text. A post with a CTA that nobody tapped and a post with a CTA that 500 people tapped count **identically**.

**Verdict — is it useless? As a performance/engagement metric, yes, essentially worthless**, and worse than worthless where the label ("CTA rate", sitting next to engagement tiles) implies it measures clicks. It measures zero about effectiveness. **The one narrow place it is legitimate:** as a *composition/consistency* signal on our own posting ("are we remembering to include a CTA?") and especially as a **competitor-style gap** ("rivals include a CTA in 90% of posts, we do 40%") — CTA-presence is a lever we fully control, so that comparison is actionable. That's the only reason to keep the number at all, and it belongs on the competitor/consistency screen, not the performance screen.

**Fixes:** (a) rename to "CTA usage / % posts with CTA" and move it off the performance page; (b) real CTA effectiveness / click-through **only exists after the §4.3 internal `/r/{id}` redirect tracker is built** — at which point this same tile becomes a true CTR and turns into the most valuable metric in the product. Until then, lean on **reactions ÷ views** (78% coverage, currently discarded — §0.5 Flaw A) as the best *available* traction proxy.

### 5.3 — The Weekly Retro panel is fully built and renders blank
`plan/page.tsx:373-466` is a genuinely sophisticated closed-loop panel — forecast accuracy (MAPE), over/under bias, plan adherence, **best hour by engagement**, **best format by engagement**, churn-vs-frequency, next-week adjustments. It returns `null` because `weekly_retros = 0 rows`. The one screen that would answer "best time by *engagement* not views" and "did last week's plan work" is dark purely because the retro job never fired (§2). Fix = fix §2; the UI is already waiting.

### 5.4 — Rich competitor metrics computed but dropped at render
`competitors/page.tsx:88-93` has an explicit comment that it drops `similarity_to_us`, CTA rate, coupon rate, and granular style rates (emoji/hashtag/multi-deal) from display though the backend keeps computing them (100 benchmark rows). Cadence *is* shown; **CTA rate, coupon rate, and similarity are the truly hidden ones.** Fix: re-add columns already present in the response type.

### 5.5 — "Best times to post" is views-only, presented as if it's engagement
`views.py:144-153` ranks by median-views/hour (honest label, good sample gate ≥3) but sits next to engagement cards, reading as an action recommendation when it only knows reach. The engagement-based version exists — inside the starved retro panel.

---

## 6. Cross-cutting / scale scaffolding

- **`org_id` appears 0 times in `src/services/`.** All planning/analytics/generation/collection run globally unscoped; the real (partial) tenancy key is `channel_id`, a late nullable additive column. `organizations`=1, `channels`=1, `users`=1. Multi-tenancy is **absent below the controller layer**, not merely shallow — and all orgs would share one Telegram session (README). Don't market "multi-channel" until one real second channel is onboarded end-to-end. (P2 — validate before selling on it, don't build more scaffolding now.)
- **Schema drift risk.** Managed by `create_all` + a hand-maintained additive-`ALTER` list, no Alembic (`migrate.py:3-4`). Any rename/constraint/non-additive change is silently uncaptured. Real deploy-safety gap for a sellable product.
- **Data hygiene.** `be/data/` holds 8 accumulating `daily_export_*.db` snapshots + 2 `tgagent.backup-*.db` (12–25 MB each). Clean up / move out of the app data dir.
- **`is_loot_deal` is 63% NULL** (144/229) because the loot threshold is a *per-batch* top-quartile needing ≥4 deals (`enrichment.py:118-120`); small batches leave it unclassifiable. Doesn't block loot posts but starves any analytics reading it. Fix: compute the threshold over a rolling window/channel history.

---

## 7. What an "Elon-tier" evaluator asks — today's honest answer

| Question | Today | After Layer 1+2 fixes | After Layer 3 (permissions + redirect tracker) |
|---|---|---|---|
| Are plans fresh and diverse? | No — frozen at 07-15, 40% off-plan, 37% blocked | **Yes** — fresh daily, on-theme, unblocked | Yes |
| Which *category* drives traction? | No — lost at `NormalizedPost` schema | Partially (add category column) | Yes, with engagement |
| CTR / revenue per post/merchant/category? | No — no click data exists | No | **Yes** — internal redirect tracker |
| Which time/merchant performs best? | No — channel-median 90% | Improving as jobs run | Yes, once outcomes populate |
| Did last week's plan work? | No — retro never ran, panel blank | **Yes** — retro fires, panel lights up | Yes, with accuracy |
| Payback per subscriber? | No — no revenue/cohort | No | Partially — needs revenue + join-source (admin-gated) |
| Can it run a 2nd channel? | No — single-tenant below controllers, one TG session | No | No (separate workstream) |
| Is the AI actually reasoning? | **Yes** — genuinely, well-guardrailed | Yes | Yes |

---

## 8. Prioritized roadmap

**TRACK A — USEFULNESS: turn it from a Telegram mirror into a deal-intelligence engine (no permissions needed; this is the "proper data" track — see §0.5).**
- A1. **Deal-dimension attribution** — extend owned-post extraction to emit `category` + `discount_band` next to the merchant/price-band it already produces; backfill the 375 posts. *(keystone)*
- A2. **Engagement-rate metric** — add reactions ÷ views as a first-class signal (reactions cover 78% of posts and are currently discarded).
- A3. **Performance leaderboards** by category / brand / price-band / discount-band / hour, ranked by engagement rate — the first non-vanity screens.
- A4. **Competitor deal-gap** — run A1's extraction over the 7,600 competitor posts; ship "rivals win with X, you're absent"; unhide the computed competitor CTA/coupon/similarity tiles.
- A5. **Rewrite plan generation** to consume A1–A4: concrete per-dimension bets + engagement targets in the weekly blueprint; kill the "~206 views" / "4.1 views" recitation in daily slot rationales.

**TRACK B — RELIABILITY / OPERATIONS (mostly not new features; makes Track A's numbers fresh and the posts actually go out):**

**P0 — operational + reliability (days, mostly not new features; transforms visible output):**
1. **Make cron jobs actually fire** — persistent scheduler / external cron / startup catch-up + `misfire_grace_time`. Un-freezes the whole intelligence layer. (§2)
2. **Timeout → not-broken** in `revalidate.py` — unblocks ~37% of posts, ~1 line. (§3.1)
3. **Fix the mislabeled block alert** ("need admin rights" → real reason). (§3.1)
4. **Loot revalidation drops the failing line, keeps the board** (mirror assembly). (§3.7)
5. **Guard link-less posts; real alert channel for no-plan days.** (§3.7)
6. **Register a `reasoning` job + relax its volume gate.** (§2)

**P0 — strategic data unlock (the thing that makes it sellable):**
7. **Internal redirect click tracker** `/r/{id}` → real CTR/clicks per post/merchant/category. (§4.3)
8. **Resolve the channel split-brain and get admin/stats rights** on the source-of-truth channel → view/join sources, forwards, and the prediction-accuracy loop start working. (§4.1)

**P1 — planner correctness + reporting truth:**
9. **Fix the weekly-persist race** (UPDATE-on-conflict; one merge path). (§3.3)
10. **Hard-enforce the 30% mix floor**; **balance `available_deals()`** by merchant/category (or wire in `DealRanker`); **add an exploration term.** (§3.4–3.6)
11. **Add `category` to `NormalizedPost`** and roll up true product-category analytics. (§5.1)
12. **Rename "CTA rate" → "CTA usage"; surface the hidden competitor CTA/coupon/similarity tiles; light up the retro panel** (falls out of #1). (§5.2–5.4)

**P2 — validate before selling on it:**
13. Onboard one real second channel with its own auth to prove multi-tenancy. (§6)
14. Alembic migrations; data-dir hygiene; rolling-window loot threshold. (§6)

---

## 9. Bottom line

The instinct that this product is "vague and only shows Telegram stats" is correct as an *experience* — but the cause is not a weak brain. There are two distinct problems, and they have different fixes:

**Usefulness (why the demo showed nothing worth showing — §0.5):** the plans only ever compute channel-average *views* and never attribute performance to any deal dimension, so every "insight" is one view number reworded. This is **fixable today with zero permissions**: you already capture reactions on 78% of posts and ignore them, and you already extract merchant/price-band from post text — extend that to category + discount-band, compute engagement *rate*, and you get real leaderboards ("70%+ off = 2× reactions," "beauty under ₹999 is your best segment") plus competitor deal-gap intelligence. That is Track A, and it's what makes the product *useful*.

**Reliability (why even the hollow plan is stale/broken — Layers 1–4):** the plan generator has been frozen since July 15 because cron never fires, a third of posts are killed by a timeout misclassification, 40% drift off-plan, and the AI's weekly blueprint is silently overwritten by the deterministic one. That is Track B, and it's what makes the useful thing *fresh and live*.

The only genuinely hard ceiling is monetization (clicks/CTR/revenue) — that needs the internal `/r/{id}` redirect tracker, and it's the one piece that isn't just analytics. Everything else you asked for — real per-category/brand/price/discount intelligence, competitor gaps, and plans that reason over measured numbers instead of reciting one average — is buildable now from data you already have. **Start with Track A1 (attach deal dimensions to real posts): it's the keystone every "proper data" feature stands on.**

---

## 10. CORE BUG LEDGER — concrete numeric/logic defects (the issues you can't see)

Every item below is a specific wrong number a user sees or a computation that silently produces one, verified against live code + `tgagent.db` (2026-07-23) with file:line, the actual wrong value, and the fix. This is the "44 vs 33.33" class, hunted across all six subsystems. **~50 defects; the root-cause clusters (§10.0) mean most collapse into ~8 fixes.**

> ### ✅ FIX STATUS (2026-07-24) — most of this ledger is now fixed in code, tests green
> **Fixed & test-verified:** fractional counts + hardcoded `/7` and `/30` denominators (now active-day divisors); `posts_delta` float garbage (rounded); `engagement_rate` fraction/percent 100× split (unified to percent); `cta_rate` 12.5%-vs-13% split (one formatter); "Best category = merchant" (now aggregated-by-merchant + relabeled "merchant") and "CTA rate"→"CTA usage"; weekly "Total views" now a true sum; retro best-hour/type sample gate + churn-day overlap; allocation & posting-window rounding now reconcile to the exact target; `is_loot` rolling-history threshold (was 63% NULL); implausible 100%/≥100 source discounts rejected; slot rescale/clamp now runs on cold-start (no more raw 71-post days); competitor `avg_views` benchmark dropped (cross-audience) + `posts_per_day` same-window comparison wired; the timeout-as-dead-deal bug that blocked 37% of posts; the "need admin rights" mislabelled alert; hard-enforced 30% mix floor; **`available_deals` now round-robins across merchants (the "always one merchant" root cause)**; the frozen-cron catch-up + `misfire_grace_time`; a registered `reasoning` cron job; the weekly-persist race (shared merge path + update-on-conflict); the slot "~4.1 views" fabrication (prompt now forbids inventing per-slot view numbers); link-less loot lines dropped; the outcome/training 24h tolerance mismatch (unified, also cuts the 65%-null outcomes).
> **Verified NOT bugs (left alone to avoid regressions):** `top_over`/`top_under` (consistent with the "over/under-performer" UI labels); `cap_per_type` (intentionally per-type); the retro "MAPE" denominator (an intentional, tested metric).
> **Deliberately deferred (need a migration or a product decision, not a silent bug):** `emoji_rate`/`hashtag_rate` rename (DB migration; hidden in UI); competitor `similarity_to_owned` z-standardization (hidden in UI); `err_views_24h` prediction-accuracy linking (blocked by the test-vs-owned channel split — a channel decision, §4.1); wiring `DealRanker` into the scheduled path and the merchant-allocator exploration term (enhancements — diversity is already addressed via `available_deals`).

### 10.0 — Root-cause clusters (fix the cluster, not the 50 symptoms)

- **C1 — Counts rendered as `int − rounded-mean` or `total ÷ fixed-divisor`** → fractional / 15-digit-float "post counts." (BUGs 1,2,3,4)
- **C2 — The same concept computed in 2–4 places over different windows/denominators, shown adjacent and unlabeled** → on-screen contradictions. (BUGs 5,6,7,8,9)
- **C3 — Fields named `_rate` that aren't in [0,1], or a rate stored as fraction in one endpoint and percent in another** → 100× / 546% renders. (BUGs 10,11,12)
- **C4 — "category" that is actually a merchant, "forwards/CTA/best-time" that measure something other than their label.** (BUGs 13–17)
- **C5 — Hardcoded day-count denominators (7, 30) and missing min-sample gates** on channels with ~10 days of history. (BUGs 18–25)
- **C6 — `round()` per-bucket with no remainder reconciliation, plus `or 1`/`max(...,0)` masks** → allocations that don't sum to the total. (BUGs 26–29)
- **C7 — Scores that look computed but are constant/NULL** (`rank_score`, `is_loot`, `price_confidence`, `validity`, `merchant_factor`) → "intelligent ranking" that's really discount-desc. (BUGs 30–35)
- **C8 — The predict→outcome→retro loop is inert and its sub-metrics are noise-on-tiny-N.** (BUGs 36–42)

### 10.1 — FLAGSHIP: the weekly "44 vs 33.33" is FOUR unreconciled posts/day numbers

On one `WeekCard` (`next/app/(dashboard)/plan/page.tsx:475-496`), the same posting data is shown four ways, each from a different formula/window, none labeled as distinct:
| On screen | Value | Source | Formula |
|---|---|---|---|
| "Avg posts/day" | **33.3** (or 20.3 mid-week) | `service.py:1100` | `posts_total / 7` (calendar ÷ **hardcoded 7**, counts zero-post days) |
| "Recommended/day" | **44** (or 35) | `service.py:1136`→`context.py:456` | `median(active days only)` |
| themes "Posts" | **34** | `campaign.py:382` | `int(round(stale lifetime baseline))` |
| digest prose | **"34.444"** | unrounded baseline into AI text | raw float in prose |
The `.toFixed(1)` on the average is why you saw a fractional post; the four-way disagreement is why the page contradicts itself. **Fix: one definition (active-day median), label the rest explicitly ("posted so far" / "planned"), never divide by a constant 7, round the digest number.**

### 10.2 — C1: Fractional / garbage COUNT renders (HIGH — user sees these)

1. **[HIGH] `day/page.tsx:142,341`** — "posts vs 30d" prints `posts_delta` unrounded (`day.py:169` = `len(rows) − round(avg,1)`). On screen: **"+6.700000000000003 posts"**, or **"−30.299999999999997 posts"** on a quiet day. → `Math.round()` it.
2. **[HIGH] `service.py:1100` + `page.tsx:477`** — `avg_posts_per_day = round(posts_total/7,1)`; ÷ hardcoded 7 deflates a partial week ~43% and renders fractional. → divide by elapsed/active days.
3. **[HIGH] `day.py:150-155`** — baseline `avg_posts_per_day = len(prior)/30` with `prior_days=30` hardcoded, but only ~10 active days exist → baseline **~11.7 vs real ~35**, understated ~3×; every "vs baseline" delta on the day page is inflated.
4. **[MED] digest** — `posting_frequency_baseline=34.444` passed unrounded into weekly digest prose; doesn't even match the plan's own `posts_per_day=34`.

### 10.3 — C2: Same metric, contradictory values on one page (HIGH)

5. **[HIGH] `analytics/page.tsx:129` vs `:244`** — `cta_rate` renders **"12.5%"** raw at :129 and **"13%"** (`Math.round`) at :244 — same field, same page. Identical bug for `deal_rate` (`:130` vs `:248`). → one formatter.
6. **[HIGH] `daily_report.py:67` vs `views.py:119`** — `engagement_rate` is a **fraction (0.0057)** from one endpoint and a **percent (0.6)** from another — 100× mismatch for the same field name.
7. **[MED] `plan/page.tsx:196-201`** — daily card shows `recommended_posts` (AI) vs `Σ slot.count` (planned) vs `scheduled_count` — e.g. "37 recommended · 33 planned · 4 short"; the three come from two engines with no enforced equality.
8. **[LOW] `campaign.py:382`** — `posts_per_week = posts*7` (238, stale baseline) sits on the same page as `totals.posts` (142 actual this week) — two week totals that never reconcile.

### 10.4 — C3: Unit / rate defects (HIGH)

9. **[HIGH] `metrics/competitor_metrics.py:117-118`** — `emoji_rate`/`hashtag_rate` are **mean counts, not rates** (owned `emoji_rate=5.464`); any `×100%` render shows **"546%"**. The code even hard-divides them by 10/5 elsewhere, proving they're known-not-rates. → rename `avg_emojis_per_post`.
10. **[MED] `analytics/page.tsx:127-129`** — "Total forwards" reads **"0"** and "Eng. rate" is built on forwards that populate on only 15/375 posts (max 1) — "not captured" shown as "nobody forwards." → hide/annotate; label eng-rate reactions-based.

### 10.5 — C4: Mislabels that drive wrong decisions (HIGH)

11. **[HIGH] `plan/page.tsx:155-157` + `daily_report.py:73-82`** — "Best/Worst category" is the **merchant of a single top/bottom post**; on single-merchant days **best == worst** (reproduced 07-17 → both "ajio"). On screen: "Best category: Ajio" (Ajio isn't a category). → aggregate by merchant, relabel.
12. **[MED] `analytics/page.tsx` "CTA rate"** — it's *% of posts containing a CTA* (`views.py:182`), not click-through; no clicks exist anywhere. → "CTA usage."
13. **[MED] "Best times to post"** (`views.py:152`) — sorted by **median views**, not engagement, but placed as an action recommendation.
14. **[LOW] `retro.py:161-163`** — `top_over`/`top_under` inverted: sorting err descending yields **under**-predicted posts labeled `top_over`.
15. **[MED] `jit_fill.py:~340`** — `rank_score` means "max discount %" on generated posts but "learned score" on `enriched_deals` — same name, two scales; anything reading across both compares apples to oranges.

### 10.6 — C5: Wrong denominators / missing sample gates (MED, on ~10 days of data)

16. **[HIGH] `intelligence/competitor.py:198` + dead `_owned_cadence_in_window` (`:216`)** — competitor `posts_per_day` is computed over the short `t.me/s` scrape window → **CKoffers 150/day, india_online_deal 128/day** vs your 37; benchmark deltas up to **+112**. The helper written to fix it has **zero callers**. → wire it in.
17. **[HIGH] `intelligence/competitor.py:44-47`** — `avg_views` benchmark compares raw views across channels of totally different audience size → deltas **+2,500…+3,888** ("you're massively behind"); one competitor logs `avg_views=2.216` (scrape artifact) treated as real. → drop or normalize by subscribers.
18. **[MED] `retro.py:196-197`** — `best_hour`/`best_type_by_engagement` have **no min-sample gate** (picks an n=1 bucket) while sibling `_adjustments` requires 5; only 87/375 posts have an engagement score.
19. **[MED] `retro.py:236-238`** — `churn_vs_frequency` uses `worst=ranked[:7]`, `best=ranked[-7:]` but only **10 distinct days exist → 4 days overlap**, making the contrast meaningless.
20. **[MED] `views.py:149-153`** — `golden_hours` needs n≥3/hour; on ~10 days most hours never qualify, yet it's still shown as "Best times" with no insufficient-data signal.
21. **[MED] `day.py:143-144`** — `type_mix` (all rows) and `merchant_mix` (drops null-merchant rows) use different denominators → their percentages aren't comparable.
22. **[LOW] `views.py:8,113`** — averages are **raw cumulative** views/post (older posts accrued more), so hour/merchant/golden-hour rankings mix post-age with performance.

### 10.7 — C6: Allocations that don't sum (MED; some latent)

23. **[MED] `campaign.py:180`** — `_allocate_posts` content_mix branch uses per-bucket `round()` with no remainder reconciliation → 18+18≠37 (banker's rounding); weekly ×7 drifts ±1-2. Its sibling `_allocate_from_recent` does it right. Latent until a `content_mix` strategy exists.
24. **[MED] `service.py:718-720`** — window redistribution `round(share*rec/raw_sum)` per window, no reconciliation, and `raw_sum … or 1`: if all window counts are 0, **every window shows 0 while the headline says the recommended total**.
25. **[HIGH] `ai_execution.py:66-79`** — slot-count clamp AND rescale are **both skipped when `recent_median is None`** (cold-start) → the model's raw unclamped counts post directly ("71 instead of 34").
26. **[MED] `ai_execution.py:35-42`** — `_rescale_slot_counts` dumps all rounding drift into the single largest slot and `max(...,0)` can break the sum (`[10,1,1]` target 2 → `[2,0,0]`).
27. **[LOW] `jit_fill.py:279-282`** — `cap_per_type` caps loot and singles **each** → effective total is 2× the intended cap.

### 10.8 — C7: Scores that look computed but are constant/NULL (HIGH — this is why ranking is fake)

28. **[HIGH] `ranking.py:135` — `rank_score` is NULL for 0/229 deals** → `DealSelector` sorts every deal by `0` → pure discount-desc; the entire learned score is inert on the scheduled path.
29. **[HIGH] `enrichment.py:119-121` — `is_loot_deal` NULL for 63% (144/229)**; the label is the top-quartile *of that batch*, so the same 55%-off deal is "loot" one day, not the next → the loot diversity bucket is starved before selection starts.
30. **[MED] `enrichment.py:159-170`** — `price_confidence_score` = **constant 1.0** for all 229 (source always complete) → any filter/threshold on it is a no-op.
31. **[MED] `ranking.py:104-110`** — `validity_factor` always 1.0 (invalids dropped upstream) → dead term in the score.
32. **[MED] `ranking.py:62-66`** — `merchant_factor` inert for **28/30 merchants** (need `sample≥20`) → per-merchant learned performance barely operates.

### 10.9 — C8: The prediction/accuracy loop is inert + noisy (HIGH)

33. **[HIGH] `outcomes.py:80` + `prediction.py:410`** — `err_views_24h` = **0/375**; all 114 predictions have `post_id=NULL`, and `backfill_post_links` matches test-channel text sha against owned-channel posts (never matches), and the backtest path never ran. The accuracy loop has computed **zero** values ever → every retro MAPE/bias is `None`.
34. **[HIGH] `outcomes.py:157-162`** — **243/375 (65%)** posts "give up" with `views_24h=NULL` because the 24h snapshot must land within **±0.75h**; any channel-level mean is then silently over the non-null 35%.
35. **[MED] `outcomes.py:34` vs `prediction.py:46`** — "24h views" is matched with **0.75h** tolerance for outcomes but **2.0h** for training → the two subsystems disagree on what "24h" means for the same post.
36. **[MED] `prediction.py:291-306`** — all predictions are `channel_median` yet stored as exact `95/304/411` **identical across every slot**, and the `/plan` UI renders them as slot-specific forecasts. → collapse to "≈411 (channel median, not slot-specific)."
37. **[MED] `outcomes.py:82`** — "MAPE" divides by **predicted, not actual**; `bias` is unbounded above → one over-performer dominates; reported with no min-N.
38. **[HIGH] slot `why` prose — the "Expect ~4.1 views" is LLM-fabricated.** The real prediction (411) is never injected into the slot rationale, so the copywriter invents an ungrounded number. → inject the real predicted value or forbid the claim in the prompt.

### 10.10 — Data-validation & competitor-similarity defects (MED/LOW)

39. **[MED] `enrichment.py:106-110`** — source discount trusted unbounded: **1 deal at 100%, 14 at ≥90%**, none sanity-checked (only the *derived* path is guarded). A 100% "free" deal persists.
40. **[MED] `ranking.py:96`** — `value_factor` clamps at 90%, so a bogus 100% deal ranks as high as the best legitimate one.
41. **[MED] `intelligence/competitor.py:50-67`** — `similarity_to_owned` (cosine) is dominated by the four unit-scale rate dims; the rest are hand-divided by 10/5/500 → "style similarity" ≈ **CTA-rate similarity** only.
42. **[MED] `intelligence/competitor.py:196`** — benchmark `delta = cv − ov` has **no per-dimension "which direction is better"** → any UI rendering sign as ahead/behind mislabels ~half the dimensions.
43. **[LOW] `competitor_metrics.py:98`** — competitors with broken view scrapes (`avg_views=2.216`) aren't gated; surfaced as real benchmark data.
44. **[LOW] `ranking.py:70-81`** — novelty/anti-repeat keys off the **owned** channel's merchants, but the engine posts to the **test** channel → the anti-repeat term fires on the wrong signal.
45. **[MED] `service.py:1098`** — weekly "Total views" is reconstructed as `Σ posts×rounded-avg`, not the true sum → drifts with post count.

**Verified clean (don't chase):** KMeans clustering is z-standardized with a fixed seed (`classifier.py:69`) — stable, not a bug. `growth.py` date range is inclusive — no off-by-one. Overview `periodTrend` and K/M subscriber compaction are correctly guarded. Prediction *magnitude* (411) is a sound channel median. Divide-by-zero is guarded in the analytics avg-views and MAPE paths.

**The five fixes that kill the most user-visible wrongness:** (1) round every count render + stop dividing by constant 7/30 [C1/C5 — kills the fractional-post class incl. your 44/33.33 and the "6.7000003 posts"]; (2) one formatter per rate + fix the `engagement_rate` fraction/percent split [C3]; (3) relabel "category"→merchant and "CTA rate"→"CTA usage" [C4]; (4) populate `rank_score`/`is_loot` on the scheduled path so ranking isn't secretly discount-desc [C7]; (5) inject the real predicted number into slot rationales and stop showing channel-median as slot-specific [C8].

### 10.11 — Who computes the broken numbers: OUR deterministic code, NOT the AI

Important for triage/blame: **almost every wrong number in this ledger is plain Python in our backend, not an AI hallucination.** The AI's only failure mode is that it faithfully *echoes* raw numbers our code hands it unrounded.

| Broken number | Computed by | Proof |
|---|---|---|
| "Avg posts/day" 33.3 (fractional, ÷7) | **our code** | `round(posts_total/7,1)` — `service.py:1100` |
| "Recommended/day" 44 | **our code** | `median(active days)` — `context.py:456` |
| themes "Posts" 34 | **our code** | blueprint baseline — `campaign.py:382` |
| "+6.700000000000003 posts" | **our code** (JS render of our float) | `day.py:169` + `day/page.tsx:142` |
| `cta_rate` 12.5% vs 13% | **our code** | two formatters — `analytics/page.tsx:129,244` |
| `engagement_rate` 100× split | **our code** | `daily_report.py:67` vs `views.py:119` |
| "category = Ajio" | **our code** | `daily_report.py:73-82` |
| `rank_score` NULL / `is_loot` 63% NULL | **our code** | `ranking.py:135`, `enrichment.py:119` |
| `err_views_24h` 0/375 | **our code** | `outcomes.py:80` linking bug |
| digest prose **"34.444 posts/day"** | **AI echoed it** — but the raw float is **ours** | we pass `posting_frequency_baseline` unrounded into the prompt context |
| slot rationale **"Expect ~4.1 views"** | **AI fabricated** | the real prediction (411) is never injected into the slot `why`, so the copywriter invents a number — `prediction.py` value never reaches the prompt (§10.9 #38) |

**Read:** of the entire ledger, exactly **one** number is genuinely AI-invented (the "~4.1 views" slot text), and even that is our fault for not feeding the real prediction into the prompt. The "34.444" in the digest is the AI parroting a raw float we should have rounded before handing it over. **Every other defect — including the fractional post count that broke the demo — is deterministic backend/UI code and fixes with rounding, one shared formatter, and correct denominators. None of it needs model tuning.** That's the good news: this is cheap, mechanical, and fully in our control.
