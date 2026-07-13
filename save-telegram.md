# Saving the Telegram Agent — Product Rescue Plan

> **Status:** Design / spec. Not yet implemented.
> **Author's intent:** Make the product coherent again — stop storing "useless text" as if it were analytics, start storing **day-wise report rows** the AI can actually reason over, and make AI a real **analyst + planner** (not just a prose writer bolted onto deterministic output). Fix the competitor pipeline so competitor data actually flows. Make the UI honest about what is AI vs computed.

---

## 0. The diagnosis in one paragraph

Today the product is two disconnected halves. One half is a **deterministic data/analytics engine** (Telethon → DB → Python stats) that mostly works for your own channel. The other half is an **AI layer** (Groq/Llama) that is almost entirely unreachable from the web app and, where it *is* reachable, only rewrites already-decided numbers into prose. Between them sits a UI that renders AI text and hard numbers **identically**, so you can't tell which is which. On top of that, the competitor pipeline is broken by a concrete bug and a scheduler mismatch, so competitor data is stale/empty and silently falls back to a degraded scrape. The result: the product "lost track" of what AI is doing, because AI is barely doing anything, and what data exists isn't shaped for reasoning.

**This plan fixes all of that around a single spine: the daily report row.**

---

## 1. Design decisions (locked)

| Decision | Choice |
|---|---|
| **AI's role** | AI as **analyst + planner** over aggregates. Deterministic code computes numbers → daily report rows → LLM reads rows, finds patterns, and generates the digest + day/week plan. AI decides *strategy*; deterministic code executes it against real inventory. |
| **Data model** | Day-wise **report rows** + keep raw **per-post rows** + add **per-post metric snapshots** (track how a post ages). Aggregates become the source of truth for planning; text is demoted to a support role (post-writing + content signals). |
| **Scope** | Everything in one plan: report spine + AI loop + competitor fetch fix + discovery accuracy + UI honesty. Phased so value lands early. |
| **Emoji/style/strategy analytics** | **Demoted to quiet inputs.** No longer headline dashboard features; they feed the AI planner and post formatter internally. |

### The one architectural rule that keeps guardrails intact

- **AI plans strategy** from report rows: how many posts, which post types, which time windows, which themes/categories to emphasize, what to watch. Output is **structured JSON**, validated against a schema.
- **Deterministic code executes** that strategy: it fills each planned slot with a **real deal from real inventory** (existing `DealRanker` / `StrategyAwareSelector` in `be/src/services/generation/engine.py`). The AI never invents a deal, price, or link.
- **Every number the AI cites is fact-checked** against the report rows it was given (see §4.3). This closes the "no automated fact-checking, prompt-only guardrail" gap that exists today (`ai.md` §5).

---

## 2. The spine: the daily report row

### 2.1 New table — `DailyChannelReport`

One row per `(channel_id, date)`. Computed nightly by a deterministic aggregator from per-post rows + metric snapshots. This is the compact, stable artifact the AI reasons over. Applies to **both** owned and competitor channels (`source_type` distinguishes them), so the AI compares you vs competitors on identical footing.

Suggested columns:

```
DailyChannelReport
  id
  channel_id            FK
  source_type           enum(OWNED, COMPETITOR)
  report_date           date (IST day boundary — reuse existing IST handling)

  # volume
  posts_count           int
  deals_posted          int              # posts that carried a real deal/link
  merchants_featured    int

  # views
  views_total           int
  views_avg             float
  views_median          float
  views_max             int
  views_min             int
  top_post_id           FK -> post (max views that day)
  bottom_post_id        FK -> post (min views that day)

  # engagement
  reactions_total       int
  forwards_total        int
  engagement_rate       float            # (reactions+forwards)/views, or views/subscriber

  # audience
  subs_start            int
  subs_end              int
  subs_net              int              # end - start

  # composition
  type_mix              json             # {single: 4, collection: 2, ...}
  category_mix          json             # {electronics: 3, fashion: 2, ...}
  posting_hours         json             # histogram of post hours (IST)
  best_category         str  (nullable)  # highest avg-views category that day
  worst_category        str  (nullable)

  # provenance
  computed_at           datetime
  data_completeness     float            # 0..1, how much of the day we actually observed
```

> **`data_completeness`** is important and new: competitor data is shallow/partial (see §5), so the AI must know when a row is only partially observed and hedge accordingly. It also feeds the fact-checker's tolerance.

### 2.2 Per-post metrics — already exist for owned, missing for competitors

**Correction after reading the schema:** `PostMetricSnapshot` **already exists** (`be/src/db/models.py:238`) with `captured_at`, `age_hours`, `views`, `forwards`, `reactions_total`, `reactions_breakdown`, and it **is** being populated for owned posts (`be/src/services/collection/telegram_owned.py:330`). So owned view-velocity/aging is already tracked — no new table needed here.

The real gap: **competitors have no equivalent.** Competitor view velocity/aging isn't tracked (only cumulative `CompetitorPost.views`). This is optional for the report spine (the daily report can be computed from cumulative views), so treat competitor velocity as a **nice-to-have later add** — either a `CompetitorPostMetricSnapshot` table or a `source_type` column generalizing the existing one. Not on the critical path.

### 2.3 Do we keep storing scraped post text? — Yes, but demoted

**Decision: keep storing raw `text` (owned `Post.text` and `CompetitorPost.text`). Do not delete it.** The instinct that "storing text is useless" is right about its *role*, wrong about *deleting it*. Text is the **ore**; the `DailyChannelReport` row + structured features are the **refined metal**. You keep the ore because:

1. **Normalization reads it.** `NormalizedPost` + `ExtractedPrice/Coupon/Link` parse the text into the structured features that feed the report, classification, learning, and the AI planner. No text → no features.
2. **Reprocessing depends on it.** The schema is built around `normalization_version` (re-run the parser over old posts when it improves). Deleting text kills this designed capability.
3. **CTA/style mining reads it.** `PostFormatter._learn_signature()` mines your last ~800 posts' text to learn your CTA/footer phrasing for new posts.
4. **Traceability (RULE 1).** Every structured row should trace back to its source text.
5. **It's cheap and unrecoverable.** Telegram text is tiny (~hundreds of MB even at 100k posts); competitor/edited/deleted history is not reliably re-fetchable. Deleting saves ~nothing and is permanent.

Its jobs going forward:
- Feed **normalization** → structured features → the report row (primary).
- Feed the AI **post writer** (`Copywriter`) and CTA/style mining with real examples.

It is **no longer** the analytics artifact or a headline display surface. "Storing text as analysis" is the mindset we remove — the report row replaces it. **Demotion, not deletion.**

**Optional future lever (YAGNI for now):** a retention window on *competitor* text (keep full text ~90 days for the analysis window, then prune old competitor text while retaining its normalized features + report rows). Keep owned text indefinitely. Only add this if storage ever becomes a real cost — it is not today.

### 2.4 The aggregator

New deterministic module, e.g. `be/src/services/analytics/daily_report.py`:
- `build_report(channel_id, date) -> DailyChannelReport` — pure function over per-post rows + snapshots for that IST day.
- Reuse the existing per-day logic in `be/src/services/analytics/day.py` (`summarize()`) as a starting point — it already computes per-merchant views/reactions/forwards, type mix, and a 30-day baseline, but its output is thrown away (never persisted, never read by the planner). **We persist it as `DailyChannelReport` and make it the planner's input.** This is the single most important wiring fix: yesterday's actuals now reach today's plan.

---

## 2.5 Full database audit — add / modify / keep / demote

I read every model file under `be/src/db/`. The headline finding: **the schema is already rich and mostly correct — this is a wiring + surfacing problem, not a schema rebuild.** Almost nothing gets deleted. Post-writing and scheduling tables are **untouched**.

### Reassurance first: post-writing & scheduling stay exactly as they are

Nothing about writing/scheduling posts is removed. These three tables are the post spine and are **kept as-is**:

| Table | File | Role — KEPT |
|---|---|---|
| `EnrichedDeal` | `models_generation.py:49` | The deal **inventory** the selector draws from to fill AI-planned slots. |
| `GeneratedPost` | `models_generation.py:88` | The **draft** (`rendered_text`, `status`, `strategy_rationale`). What Drafts page shows, what gets published. |
| `ScheduledPost` | `models_automation.py:45` | The **send queue** — idempotency, retry/backoff, publish status. The automated-posting machinery. |

The AI planner produces *strategy* (slots); this spine still produces and schedules the *actual posts*. The only change touching them is optional: let `Copywriter` (AI, real fields only) write `rendered_text` as a toggle instead of the template formatter.

### ADD — 1 new table (the genuine gap)

| Table | Why it's needed |
|---|---|
| **`DailyChannelReport`** (§2.1) | Does not exist. This is the day-wise aggregate row the AI reasons over (owned + competitor via `source_type`). `day.py:summarize()` computes essentially this today but **throws it away** — we persist it. This is the spine. |

### MODIFY — extend existing tables (no new plan store needed)

| Table | Change | Why |
|---|---|---|
| `CampaignPlan` (`models_campaign.py:64`) | Add columns: `ai_digest` (Text), `cited_numbers` (JSON), `factcheck_status` (String), `is_ai_generated` (Boolean), `report_ids` (JSON — which `DailyChannelReport` rows fed it), **`adherence` (JSON)** and **`reconciliation` (JSON)** for the closed-loop feedback (§3.5). | It **already** stores daily/weekly/event plans with a `blueprint` JSON, `expected_outcome`, `confidence`, `target_date`, and is already served by `/api/plans` + `/api/weekly`. Reuse it as the AI plan+digest store instead of inventing a new table. The AI's structured day/week plan goes in `blueprint`; the narrative digest + fact-check provenance + plan-vs-actual reconciliation go in the new columns. `expected_outcome` already exists — the loop just starts reading it back. |
| `Competitor` (`models.py:293`) | Add `resolution_confidence` (Float) + `verified_by` (String: `heuristic`/`ai`/`manual`). | Discovery accuracy (§4.3) — stop trusting fuzzy guesses blindly; record how a handle was resolved and how confident. |
| (optional) competitor velocity | `CompetitorPostMetricSnapshot`, or generalize `PostMetricSnapshot` with `source_type` | Nice-to-have (§2.2); off the critical path. |

### KEEP AS-IS — the working spine (data, infra, tenancy)

Owned data: `Channel`, `Post`, `PostMetricSnapshot`, `ChannelStatSnapshot`, `ParticipantSnapshot`.
Competitor raw: `Competitor`, `CompetitorPost`.
Normalization/classification (feeds report composition + slot selection): `NormalizedPost`, `ExtractedPrice`, `ExtractedCoupon`, `ExtractedLink`, `PostTypeCluster`, `PostClassification`.
Merchants/deals: `Merchant`, `MerchantProduct`, `ProductPriceSnapshot`, `AffiliateLink`.
Planning input: `SaleEvent` (India deal calendar — feeds event plans).
Infra/tenancy: `RawSnapshot`, `CollectionJob`, `CollectionEvent`, `SchedulerRun`, `Organization`, `User`.

### KEEP but DEMOTE — tables stay as AI *inputs*, their dedicated UI is removed

Your instinct ("emoji analytics / strategy feel useless, text is useless") is right **as a UI/feature judgment**, not as a data-deletion instruction. Deleting these would break the deterministic engines that still compute report composition, slot constraints, and post formatting. So: **keep the tables, feed them to the AI planner as the "menu of facts," remove their headline dashboard surfaces.**

| Table | New role | UI |
|---|---|---|
| `ChannelStyleProfile` (`models_learning.py:33`) | Quiet input to post formatter + planner (emoji/CTA/cadence). | Remove "emoji/style analytics" section. |
| `PostTypePerformance` (`models_learning.py:67`) | Input: which post types perform → planner slot types. | Fold into report/plan, no standalone page. |
| `LearningRecord` (`models_learning.py:91`) | Input: timing/CTA/emoji learnings → planner context. | Internal. |
| `GrowthStrategy` / `GrowthRecommendation` (`models_growth.py`) | Input: content-mix targets become **slot constraints** for the AI planner. AI's plan supersedes it as the user-facing "strategy." | Demote the "strategy" headline; keep recommendations as supporting evidence. |
| `ReasonedInsight` (`models_reasoning.py:21`) | Input: "what changed & why" → digest context. | Feeds the AI digest instead of its own raw list. |
| `MerchantProfile` / `MerchantMetricWindow` / `MerchantOpportunity` | Input: merchant performance → planner emphasis. | Keep merchant view; de-emphasize. |
| `CompetitorProfile` / `CompetitorBenchmark` / `CompetitorSignal` | Input: competitor behaviour → digest "competitor note" + comparison. | Keep, but driven off report parity (§4.4). |

### REMOVE — none

**No tables should be dropped.** The "useless" analytics are useless *as things you stare at*, not as *inputs the agent reasons over*. Removing them removes the AI planner's evidence. Text is likewise kept (Copywriter + normalization both read it). The rescue is **reshaping what's surfaced and who consumes it**, not deleting storage.

### Net schema delta

- **+1 table** (`DailyChannelReport`)
- **~7 columns** on `CampaignPlan` (incl. the two for closed-loop feedback), **2 columns** on `Competitor`
- **0 tables removed**
- Everything else: keep; the work is *wiring* (persist `day.py`'s output, feed reports to AI, cascade the pipeline) and *surfacing* (AI badge, digest page, drop demoted UI).

---

## 3. The AI agent loop (the real shift)

### 3.1 What the AI produces

Three **structured** artifacts, all grounded in report rows:

1. **Daily digest** — "how yesterday went" + "so here's the focus today." Grounded in yesterday's `DailyChannelReport` vs a trailing baseline (e.g. 7/30-day average of the same columns).
2. **Day plan** — structured JSON the pipeline executes:
   ```json
   {
     "date": "2026-07-08",
     "post_slots": [
       {"type": "single", "window_ist": "12:00-13:00", "theme": "electronics", "why": "..."},
       {"type": "collection", "window_ist": "19:00-20:00", "theme": "fashion", "why": "..."}
     ],
     "emphasis": "push electronics — 2.1x your avg views yesterday",
     "watch": "forwards down 30% w/w",
     "cited_numbers": [2100, 980, 0.30]
   }
   ```
3. **Weekly digest + plan** — same idea at week granularity: biggest win, biggest concern, what's working, what to change, competitor note, and a week-level slot allocation.

### 3.2 Execution: AI plan → real posts

- The **day plan slots** are passed to the existing deterministic generator (`be/src/services/generation/engine.py` + `daily_planner.py`). Each slot's `{type, window, theme}` becomes selection constraints; `DealRanker`/`StrategyAwareSelector` fill it with a **real, in-inventory deal**.
- If AI asks for a slot with no matching inventory, the deterministic layer degrades gracefully (nearest category / drop slot) and records why. AI never fabricates the content.
- Post text is still assembled by `PostFormatter` (template) **or** optionally by the now-wired `Copywriter` (AI, real fields only) — that becomes a config toggle, not a rewrite.

### 3.3 The fact-checker (new, closes a real gap)

Because outputs are structured with an explicit `cited_numbers` array:
- A deterministic validator checks every cited number actually appears in the report rows handed to the model (within tolerance scaled by `data_completeness`).
- On mismatch → reject and either retry once or fall back to the deterministic digest/plan. Today there is **zero** fact-checking (`ai.md` §5); this makes the "no hallucinated numbers" guarantee *enforced*, not just *requested*.

### 3.4 Reuse the existing AI plumbing

- Keep `be/src/ai/client.py` (single choke point, grounding system prompt, temperature 0.3, deterministic-fallback discipline). **Do not rewrite it.**
- Extend `be/src/ai/context.py` with getters that return **report rows** (owned + competitor) instead of only the current profile/learning blobs. Report rows become the AI's primary menu of facts.
- The daily/weekly generators evolve from `be/src/ai/briefing.py` (`BriefingGenerator`) — but return **structured** output (schema-validated), not free text. `plan.md`/`fix.md` already flagged wanting structured briefing fields; this delivers it.
- Fix the dead-config note: remove the unused `ANTHROPIC_API_KEY` path or wire it as a real fallback provider (decide during implementation; low priority).

### 3.5 Closed-loop feedback — plan → measure → correct (the piece that actually grows the channel)

§3.1–3.4 describe a daily **cycle** that re-reads fresh data each day. That is *open-loop*: the AI is informed by recent history but never learns whether its **own past plans worked**, so it makes the same quality of plan forever. This section closes the loop so the agent gets better at *your* channel over time.

**Every day, before it plans, the agent assembles a reconciliation block from yesterday:**

1. **What was planned** — yesterday's `CampaignPlan` (its slots + `expected_outcome`, e.g. "6 posts, push electronics, expect ~+15% views on that type").
2. **What actually happened** — yesterday's `DailyChannelReport` row (real posts, views, forwards, reactions, mix).
3. **How much of the plan synced (adherence)** — a **deterministic** comparison of the planned slots against the posts actually published (`GeneratedPost` / `ScheduledPost` for that date): count, types, and time windows. e.g. *"planned 6 posts across 3 windows → 4 published, the 2 evening-slot posts never went out."* This is fact, not AI.
4. **Expected vs actual (attribution)** — a **deterministic** diff of each `expected_outcome` against the report. e.g. *"predicted electronics +15% views → actual +3%."*
5. **Reconciliation summary** — the AI narrates plan vs execution vs outcome and offers a hypothesis for the gaps (grounded, fact-checked like every other AI number).

**Then it produces today's plan** with that reconciliation prepended to the prompt. Over days the agent sees its own hit/miss history and self-corrects — it stops over-promising on a post type that never delivers, notices a time window that's consistently missed and re-allocates, and leans into what actually moved engagement.

**This is exactly the shape you described:** *yesterday's actuals → what was planned → how much synced → summary of that → today's plan.*

```
   yesterday's PLAN (expected_outcome) ──┐
   yesterday's REPORT (actuals) ─────────┤
   adherence: planned vs published ──────┼──► reconciliation ──► TODAY'S PLAN
   expected vs actual (attribution) ─────┘        (AI summary)        │
        ▲                                                             │
        └───────────── tomorrow, this plan becomes "yesterday" ───────┘
```

**Honesty guardrails on the loop:**
- **Adherence is deterministic** (code compares plan to published posts) — never an AI claim.
- **Attribution is correlational, not causal.** Engagement is multi-causal (time of day, deal quality, external events). The loop surfaces *"planned X, did Y, got Z"* — it must **not** assert *"the plan caused Z."* Carry sample size + a confidence caveat, same as the rest of the system.
- The loop tunes *future prompts and priorities*; it does not silently mutate the deterministic selector.

**Data:** `expected_outcome` already exists on `CampaignPlan` (`models_campaign.py:77`) — it's just never read back. Closing the loop needs two more columns (see §2.5): `adherence` (JSON) and `reconciliation` (JSON) on `CampaignPlan`. No new table.

---

## 4. Competitor pipeline fixes (in scope)

### 4.1 Fix the confirmed Telethon blocker — quick win, do first

`be/src/services/collection/telegram_competitor.py:104-106`:
```python
async with asyncio.get_event_loop().run_in_executor(None, self._update_from_entity, comp_id, entity):
    pass
```
`run_in_executor(...)` returns a **Future**, which is not an async context manager → raises `AttributeError` on **every** competitor fetch → swallowed by the broad `except` at `:110` → function returns `None`. Effect: the system thinks Telethon always fails, always double-fetches via the degraded t.me/s scrape, and **never marks competitors `AVAILABLE`** (`_update_from_entity` never runs).

**Fix:** `await` the future, or just call the sync method directly:
```python
self._update_from_entity(comp_id, entity)   # it manages its own session_scope
```
Also: catch `FloodWaitError` explicitly (it's imported at `:75` but never handled) and stop treating flood-waits as "Telethon failed → scrape."

### 4.2 Fix the scheduler mismatch

- `be/src/services/collection/scheduler.py` (used by `tgagent run`) fetches **only** the `.env` `COMPETITOR_CHANNELS` list — DB-discovered competitors are stored but **never fetched**.
- `be/src/controllers/schedulers.py` `j_competitor_sync` fetches both.
- **Fix:** unify on one fetch path that always reads DB competitors + env list. Discovered handles must actually get fetched regardless of which scheduler runs.

### 4.3 Fix discovery accuracy — the legitimate place for AI

Today handle resolution is fuzzy string matching with a weak gate: `resolve_username` (`discovery.py:294-339`) accepts `candidates[0]` unless `sim < 0.3 AND relevance < 2` (`:327-333`) — so a generic "India Deals Loot" beats the real brand channel.

**Fix (two layers):**
1. **Raise the deterministic bar:** require higher similarity, sanity-check participant count and recent-post recency before accepting.
2. **AI as verifier (new, high-value AI use):** for ambiguous candidates, ask the LLM a **structured yes/no + confidence**: *"Here are candidate channels (titles, usernames, descriptions). Which, if any, is the official channel for brand X? Answer with the username or `none`, plus confidence."* This is a genuine judgment task AI is good at — unlike today, where AI does *none* of the discovery. Store the confidence; low-confidence matches are flagged, not silently trusted.

### 4.4 Chain the pipeline correctly

Today: `discover → fetch → normalize → classify → intel → dashboard` is 5 hops across independent cron jobs, none triggering the next, and `j_competitor_intel` runs discovery **then immediately** builds profiles in the same tick — so a just-discovered competitor has zero normalized posts and is skipped for a day+.

**Fix:**
- Separate discovery from profile-building (don't run them in the same tick).
- After fetch+normalize completes for a competitor, *then* trigger intel for it.
- Generate `DailyChannelReport` rows for competitors too (source=COMPETITOR), so the dashboard and the AI read the **same** report artifact for you and them. This also fixes the "dashboard only reads `CompetitorProfile`, so fetched-but-unprofiled competitors are invisible" problem (`comparison.py` full-window path).

---

## 5. UI honesty (make AI vs computed visible)

Currently **no page** distinguishes AI-written text from computed numbers — same Card/Badge/Text styling everywhere (all 7 dashboard pages). The only AI-aware artifact is the `ai_summary` field on the Plan page, and even it shows no "AI" label to the user.

**Fixes:**
1. Add an **`AI` badge / treatment** to the shared component kit (`next/components/ui/`) — a distinct visual token (icon + label) applied to any AI-authored block (digest, plan reasoning, competitor verdict).
2. Add a **Daily Digest** surface to the dashboard — this is the "how yesterday went → what to do today" view that does not exist today. Backed by the new structured daily digest/plan artifacts. (The `/api/job` briefing path is ~90% wired but unused by the frontend; either use it or add a dedicated `/api/digest` route.)
3. Computed numbers stay unbadged. The rule: **if a human/LLM wrote the words, it wears the AI badge; if Python computed the number, it doesn't.**

---

## 6. What gets demoted / removed

- **Emoji / CTA / style analytics:** keep the computation as **quiet inputs** to the post formatter and AI planner; **remove their dedicated dashboard sections.** No user-facing "emoji analytics" feature.
- **Deterministic strategy blueprint engine:** demoted. Its content-mix output becomes a **candidate-generation input** to the AI planner (helps constrain slots to sane categories), not a headline "strategy" feature. AI reasoning over report rows becomes the actual strategy.
- **The "text as analytics" mindset:** removed. Text persists only for post-writing + content signals.

---

## 7. Phasing (one plan, sequenced for early value)

**Phase 0 — Unblock competitor data (days, not weeks):**
- Fix the Telethon `async with` bug (§4.1).
- Fix the scheduler mismatch so DB competitors get fetched (§4.2).
- Add `FloodWaitError` handling; stop silent scrape-fallback on transient errors.
- *Verification:* run one competitor collection, confirm `source="telethon"` events fire and competitors flip to `AVAILABLE`.

**Phase 1 — Build the report spine:**
- `DailyChannelReport` + `PostMetricSnapshot` tables + migration.
- `daily_report.py` aggregator (evolve `day.py`'s `summarize()`); persist nightly for owned + competitor channels.
- Point ANALYTICS collection at `PostMetricSnapshot` instead of clobbering post rows.
- *Verification:* report rows populate with correct totals/max/min against a known day.

**Phase 2 — AI analyst + planner loop:**
- Extend `ai/context.py` with report-row getters.
- Structured daily/weekly digest + day/week plan generators (evolve `briefing.py`), schema-validated.
- The fact-checker (§4.3 → §3.3) validating `cited_numbers`.
- Wire AI day-plan slots → deterministic `engine.py` execution against real inventory.
- *Verification:* AI plan cites only real numbers (fact-checker green), and generated drafts fill AI-planned slots with real deals.

**Phase 2.5 — Close the loop (§3.5):**
- Deterministic **adherence** computation: planned slots vs actually-published posts for the date.
- Deterministic **expected-vs-actual** attribution against the report row.
- Feed the reconciliation block into the next day's planning prompt; store `adherence` + `reconciliation` on the plan.
- *Verification:* on day N+1, the digest correctly reports what was planned, what published, and where the prediction missed — and the day N+1 plan visibly references it.
- *Note:* needs ≥2 days of live plans to exercise; stand it up right after Phase 2 and let it accrue.

**Phase 3 — Competitor accuracy + parity:**
- AI verifier for discovery (§4.3); confidence stored and surfaced.
- Correct pipeline chaining/ordering (§4.4).
- Competitor `DailyChannelReport` rows feeding the same dashboard + AI comparison.

**Phase 4 — UI honesty:**
- `AI` badge component; apply to all AI-authored blocks.
- Daily Digest dashboard surface + route.
- Remove emoji/style dashboard sections; demote strategy blueprint UI.

---

## 8. Flaws this plan closes (traceability)

| Flaw (from audit) | Closed by |
|---|---|
| AI is a writer, never an analyst/planner | §3 — AI reasons over report rows and produces the plan |
| No daily digest; yesterday's actuals never reach today's plan | §2.4 (persist `day.py` output) + §3.1 |
| Planning is open-loop — AI never learns if its own plans worked | §3.5 closed-loop feedback (adherence + expected-vs-actual → next plan) |
| No fact-checking of AI output (prompt-only guardrail) | §3.3 fact-checker on `cited_numbers` |
| Text stored as if it were analytics | §2 (report rows are the artifact; text demoted, not deleted) |
| Competitor view-velocity/aging untracked | §2.2 (optional `CompetitorPostMetricSnapshot`; owned already tracked) |
| AI plan/digest not persisted or shown honestly | §2.5 (extend `CampaignPlan` with AI + fact-check columns) |
| Competitor Telethon fetch silently fails every run | §4.1 bug fix |
| DB-discovered competitors never fetched | §4.2 scheduler unify |
| Discovery picks wrong channel (weak fuzzy gate) | §4.3 AI verifier + stricter gate |
| Fetched-but-unprofiled competitors invisible on dashboard | §4.4 competitor report rows |
| UI can't tell AI text from computed numbers | §5 AI badge + digest surface |
| Emoji/style/strategy presented as headline value | §6 demote to inputs |

---

## 9. Explicit non-goals (YAGNI)

- No new AI provider migration (keep Groq/Llama via existing `client.py`); the `ANTHROPIC_API_KEY` dead-config cleanup is optional and low priority.
- No rewrite of `client.py`, `PostFormatter`, `DealRanker`, or `StrategyAwareSelector` — they are reused.
- No multi-account / bot-token Telegram work — the existing user-session auth is correct for reading public channels.
- No conversational/session-memory coach in this plan (the CLI `GrowthCoach` stays as-is until the report+plan loop proves out).

---

## 10. Risks & open bets (read this before believing the plan is a silver bullet)

This plan removes the architectural rot and the *known* bugs, and it gives the product a real chance to grow the channel. It is **not** a guarantee. Being honest about what it does and doesn't settle:

**What it reliably delivers**
- The confirmed Telethon bug and the structural breaks (scheduler mismatch, discarded `day.py`, orphaned AI) are fixed — these are mechanical.
- The product becomes **coherent and honest**: AI genuinely in the loop, data flowing, a UI that distinguishes AI from computed. This solves the original "I lost track of what AI is doing" problem.
- The metrics it optimizes (views, forwards, reactions, subscriber trend) **are** the right success metrics for a growth/engagement goal — the goal and the instrumentation are aligned.

**Open bet #1 — recommendation quality is unproven until tested.** The fact-checker stops fabricated numbers; it does **not** guarantee good *judgment*. A plan can be perfectly grounded and still be generic. Prompting helps, but the real quality levers are, in order: (1) the **features present in the report rows**, (2) **model capability** (Llama-3.3-70B is capable, not frontier), (3) prompt wording. **Mitigation:** evaluate real AI plans on real data after Phase 2 before building further; the closed loop (§3.5) is what compounds quality over time. Consider a human thumbs-up/down on plans as an extra signal.

**Open bet #2 — attribution is correlational.** Engagement is multi-causal. The closed loop surfaces "planned X, did Y, got Z"; it cannot prove the plan *caused* the outcome. Treat the loop as a steering aid, not proof. Guard against the AI narrating correlation as causation.

**Known ceiling — no revenue/click signal.** MTProto gives no affiliate click/conversion data (`AffiliateLink.clicks` stays NULL unless entered manually). For a **growth/engagement** goal this is fine — it's the right target. If the goal ever shifts to **revenue**, that signal must come from outside Telegram (affiliate dashboards / shortener), and this architecture would need a revenue-data intake to optimize it. Out of scope now, by design.

**Known ceiling — competitor data stays shallower than owned.** Even with the bug fixed, competitor fetch runs on a user session subject to FloodWaits, private/banned channels, and the t.me/s fallback (no forwards/reactions). "Parity with your own channel" is aspirational; competitor signals should always carry lower confidence.

**Growth vs engagement — set expectations.** The architecture most credibly moves **engagement** (views/reactions/forwards — directly controllable by posting decisions). **Subscriber growth** is downstream and multi-causal (discovery, cross-promo, virality). Forwards are the bridge you *can* influence. Frame the goal as "drive engagement and forwards, which pull subscriber growth" — not "the AI directly grows subscribers."

**Not exhaustively bug-checked.** The audits were read-only static reads; one bug was verified by reading code, but the system was not run and no tests were executed. Expect more bugs in paths not exercised here. Phase 0's verification step is the first real test.

**The honest bottom line:** implement Phase 0–2, then **judge the AI plans on your real data.** If they're good, the rest is worth building and the closed loop makes them better. If they're generic, you've learned that cheaply and can rethink the AI approach (better features, better model, tighter prompts) before committing to the full build.
