# DealWing / GrabOn — Architecture

One-line version: **Telegram (ours + competitors) + merchant deal API → normalize → analyze/AI → AI daily plan → just-in-time fresh posting → dashboard.**

> The AI plan is now the **source of truth for scheduling** (not a dashboard-only artifact). Each planned slot is filled with freshly-scraped inventory ~3 minutes before it fires and written by the AI copywriter (template fallback). Publishing to Telegram is wired end-to-end but the final send is **intentionally gated** (admin-rights + operator sign-off) — see §4/§5.

---

## 1. System at a glance

```mermaid
flowchart LR
    subgraph SRC["External sources"]
        TG_OWN["Telegram\n(our channel)\nMTProto"]
        TG_COMP["Telegram\n(competitor channels)\nMTProto / t.me/s scrape"]
        DEAL_API["GrabCash Deals API"]
        MERCH["Merchant sites\n(Amazon, Flipkart, Boat...)"]
    end

    subgraph COLLECT["Collection layer (services/collection/)"]
        C1["OwnedChannelCollector"]
        C2["CompetitorCollector"]
        C3["DealSourceClient"]
        C4["MerchantEnrichmentCollector"]
        C5["LinkResolutionEngine"]
    end

    subgraph RAW["Raw storage"]
        T_POSTS[("posts")]
        T_CPOSTS[("competitor_posts")]
        T_DEALS[("enriched_deals")]
        T_MERCH[("merchant_products")]
        T_SUBS[("participant_snapshots\n+ daily_subscriber_stats")]
    end

    subgraph XFORM["Transform layer (services/processing/, classification/)"]
        NORM["PostNormalizer"]
        CLASS["PostClassifier (k-means)"]
    end

    subgraph DERIVED["Normalized storage"]
        T_NORM[("normalized_posts\n+ prices/coupons/links")]
        T_CLUS[("post_classifications")]
    end

    subgraph ENGINES["Analytics + Intelligence (services/analytics/, intelligence/)"]
        E1["day / views / growth\n(request-time reads)"]
        E2["Merchant / Competitor\nIntelligence engines"]
        E3["Growth + Reasoning\nengines"]
        E4["Daily report builder"]
    end

    subgraph AI["AI layer (ai/)"]
        CTX["context.py\n(read-only bundlers)"]
        GROQ["AIClient → Groq LLM"]
        OUT["Planner (day+week) /\nBriefing / Coach"]
        COPY["Copywriter\n(write_for_item)"]
    end

    subgraph AUTO["Just-in-time posting (services/generation/, automation/)"]
        JIT["jit_fill\n(fill slot with fresh deal\n~3 min before it fires)"]
        PUB["Publisher\n(send gated)"]
    end

    subgraph API["FastAPI (routers/data.py)"]
        APIR["/analytics /day /growth\n/plan /competitors /drafts ..."]
    end

    subgraph FE["Next.js dashboard"]
        PAGES["/analytics /day /growth\n/plan /competitors ..."]
    end

    TG_OWN --> C1 --> T_POSTS
    TG_OWN --> C1 --> T_SUBS
    TG_COMP --> C2 --> T_CPOSTS
    DEAL_API --> C3 --> T_DEALS
    MERCH --> C4 --> T_MERCH
    T_POSTS --> C5
    T_CPOSTS --> C5
    C5 --> T_NORM

    T_POSTS --> NORM
    T_CPOSTS --> NORM
    NORM --> T_NORM
    T_NORM --> CLASS --> T_CLUS

    T_NORM --> ENGINES
    T_CPOSTS --> ENGINES
    T_SUBS --> ENGINES
    T_CLUS --> ENGINES
    ENGINES --> DERIVED2[("growth_strategies,\nreasoned_insights,\nmerchant/competitor profiles,\ndaily_channel_reports")]

    DERIVED2 --> CTX
    T_DEALS --> CTX
    CTX --> GROQ --> OUT
    OUT --> T_PLAN[("campaign_plans\n(AI day + week plan)")]

    T_PLAN --> JIT
    T_DEALS --> JIT
    JIT --> COPY
    COPY --> JIT
    JIT --> T_GP[("generated_posts")]
    T_GP --> T_SP[("scheduled_posts")]
    T_SP --> PUB
    PUB -.gated.-> TG_OWN

    ENGINES --> APIR
    T_PLAN --> APIR
    T_GP --> APIR
    APIR --> PAGES
```

**Key fact:** schedulers are **off by default** (`SCHEDULERS_AUTOSTART=false`). Nothing above runs automatically until the registry is started — see §4.

---

## 2. What data we pull, from where

| Source | Method | Collector | What we get | Writes to |
|---|---|---|---|---|
| **Our own channel** | Telegram MTProto (Telethon, logged-in session — full access) | `OwnedChannelCollector` | Full post history, live views/forwards/reactions, subscriber count, admin stats | `posts`, `post_metric_snapshots`, `participant_snapshots`, `daily_subscriber_stats` |
| **Competitor channels** | MTProto if visible, else public `t.me/s` HTML scrape (approximate views only) | `CompetitorCollector` | Post text, approximate views (`views_text`) or exact views if Telethon works | `competitor_posts` |
| **New competitors** | Telegram search + AI-assisted handle verification, **or** manual add via Settings → Competitors (`POST /api/competitors`) | `discovery.py`, `services/collection/onboarding.py` | New candidate channels, classified Direct (platform) vs Indirect (channel-only). A manually-added competitor immediately runs a one-time 7-day backfill + link-resolution + normalization + intelligence pass, then falls into the normal scheduler like any other competitor. | `competitors` |
| **Deal catalogue** | GrabCash Deals API (httpx, Camoufox stealth-browser fallback on 403) | `DealSourceClient` → `DealEnrichmentEngine` | Priced, validated, ranked deal objects | `enriched_deals` |
| **Merchant product pages** | Per-merchant scrapers (Amazon/Flipkart/Boat/Reliance); Ajio/Nykaa/Croma/Zepto/Blinkit are **known-blocked**, never scraped | `MerchantEnrichmentCollector` | Price, MRP, availability | `merchant_products`, `product_price_snapshots` |
| **Shortlinks in our posts** | Async httpx redirect-following — HTTP 3xx **plus** `<meta http-equiv=refresh>` / simple-JS (`window.location`, `location.replace`) bounces (≤2 extra hops, honors the refresh delay capped at 2s), cached | `LinkResolutionEngine` | Final resolved URL → merchant domain (`tldextract` fallback for unlisted domains) | `extracted_links`, `discovered_domains`, backfills `normalized_posts.primary_merchant_key` |

---

## 3. Database map (grouped)

```mermaid
flowchart TB
    subgraph G1["Raw ingestion"]
        posts["posts (owned)"]
        cposts["competitor_posts"]
        pms["post_metric_snapshots"]
        rs["raw_snapshots"]
    end

    subgraph G2["Growth tracking"]
        psnap["participant_snapshots"]
        dss["daily_subscriber_stats\n(subs_start/end/joined/left)"]
    end

    subgraph G3["Normalized / derived"]
        np["normalized_posts"]
        ep["extracted_prices / coupons / links"]
        dd["discovered_domains"]
        ptc["post_type_clusters\n+ post_classifications"]
    end

    subgraph G4["Merchant / deal data"]
        merch["merchants"]
        mprod["merchant_products\n+ price_snapshots"]
        ed["enriched_deals"]
        aff["affiliate_links"]
    end

    subgraph G5["Intelligence outputs"]
        mp["merchant_profiles /\nmetric_windows / opportunities"]
        cp["competitor_profiles /\nbenchmarks"]
        csp["channel_style_profiles /\npost_type_performance / learnings"]
        gs["growth_strategies /\nrecommendations"]
        ri["reasoned_insights"]
        dcr["daily_channel_reports"]
    end

    subgraph G6["AI + automation"]
        cplan["campaign_plans\n(AI planner output)"]
        gp["generated_posts"]
        sp["scheduled_posts"]
        sr["scheduler_runs"]
    end

    subgraph G7["Org / auth"]
        org["organizations"]
        users["users"]
        chan["channels"]
    end

    posts --> np
    cposts --> np
    np --> ptc
    G3 --> G5
    G1 --> G5
    G2 --> G5
    G4 --> G5
    G5 --> dcr
    G5 --> cplan
    ed --> gp --> sp
```

| Group | Table | Purpose |
|---|---|---|
| Raw ingestion | `posts` | Every message on our owned channel, latest observed metrics |
| | `competitor_posts` | Every message we could see on tracked competitor channels |
| | `post_metric_snapshots` | View/forward/reaction time series per owned post (velocity) |
| | `raw_snapshots` | Immutable pointer to raw payload on disk (audit trail) |
| Growth tracking | `participant_snapshots` | Point-in-time subscriber count |
| | `daily_subscriber_stats` | Per-day joined/left/net, upserted every sync cycle |
| Normalized | `normalized_posts` | Structured view of one post: emojis, hashtags, CTA, price flags, merchant match |
| | `extracted_prices/coupons/links` | Parsed sub-entities of a normalized post |
| | `discovered_domains` | Domains seen via link-resolution that aren't in the static merchant list yet |
| | `post_type_clusters`/`post_classifications` | Learned (k-means) post-type labels |
| Merchant/deal | `merchants` | Static registry: which merchants we can/can't scrape |
| | `merchant_products`+`price_snapshots` | Product price history |
| | `enriched_deals` | Validated, ranked deals ready to post |
| | `affiliate_links` | Short→resolved URL + broken-link flag |
| Intelligence | `merchant_profiles`/`opportunities` | Per-merchant performance + AI-flagged opportunities |
| | `competitor_profiles`/`benchmarks` | Us-vs-them behavior comparison (the old `competitor_signals` table was removed — static, no analytical value) |
| | `channel_style_profiles`/`post_type_performance`/`learning_records` | What's working on our own channel |
| | `growth_strategies`/`recommendations` | Ranked growth actions |
| | `reasoned_insights` | "Why did this metric move" narratives |
| | `daily_channel_reports` | Nightly aggregate per channel per day — the AI's main data diet |
| AI/automation | `campaign_plans` | AI-generated daily **and** weekly posting plan, fact-checked against reports; the daily plan's `post_slots` drive `jit_fill` |
| | `deal_scores` | Audience-fit score history per deal (`DealScoringEngine`); feeds planner `scored_deals` |
| | `generated_posts`/`scheduled_posts` | JIT-filled draft → queued → published post pipeline |
| | `post_predictions`/`post_outcomes` | Baseline view/forward prediction per draft + measured T+1h/6h/24h actuals (the latter also feed velocity-based learning) |
| | `weekly_retros` | Last week's predictions vs actuals (weekly retro) |
| | `scheduler_runs` | Audit log of every cron execution |
| Org/auth | `organizations`/`users`/`channels` | Multi-tenant config |

---

## 4. Schedulers — the cron pipeline

All jobs live in `src/controllers/schedulers.py` (APScheduler, IST). **Disabled unless `SCHEDULERS_AUTOSTART=true`.**

```mermaid
flowchart TD
    A["telegram_sync (5m)\ncompetitor_sync (10m)"] --> B["normalize_posts (5m)"]
    B --> C["link_resolution (15m,\nenv-configurable)"]
    B --> D["stats_refresh (30m)"]
    C --> E["merchant/competitor\nintelligence (daily 06:30/07:00)"]
    B --> F["learning (daily 02:00)\n(prefers T+24h velocity)"]
    STAT["outcome_collector (15m)\nT+1h/6h/24h view snapshots"] --> F
    F --> G["growth_detection (daily 05:30)"]
    E --> G
    RPT["daily_report (daily 05:15)"] --> I["daily_plan (daily 06:00)\nAI plan → per-post slots\n(window/type/theme/merchant)"]
    G --> I
    K["merchant_feed_sync (30m)\ndeal_ranking (30m)"] --> JIT["jit_fill (1m)\nfill each due slot with a FRESH deal\n+ AI copy → generated_posts → enqueue"]
    I --> JIT
    JIT --> L["queue_processor (1m)\npublish scheduled_posts\n(send gated on admin + sign-off)"]
    I --> J["ai_daily_summary (08:00)\nweekly_report (Mon 08:30,\n+ AI weekly plan)"]
    M["db_cleanup (daily 03:00)\norg_health (1h)\nurl_health (12h)"] -.housekeeping.-> A
```

| Job | Cadence | Does | Status |
|---|---|---|---|
| `telegram_sync` | 5 min | Pull new owned-channel posts | Live |
| `competitor_sync` | 10 min | Pull new competitor posts | Live |
| `normalize_posts` | 5 min | Raw → `normalized_posts` | Live |
| `link_resolution` | 15 min (`LINK_RESOLVE_INTERVAL_MIN`) | Resolve shortlinks → merchant | Live |
| `stats_refresh` | 30 min | Re-check views/forwards/reactions on recent posts | Live |
| `merchant_feed_sync` | 30 min | Pull + enrich deal feed | Live |
| `deal_ranking` | 30 min | `DealScoringEngine` — persist an audience-fit `DealScore` per active deal (feeds `/deals/scored` + planner `scored_deals`) | Live |
| `outcome_collector` | 15 min | Advance `post_outcomes` through T+1h/6h/24h view snapshots (feeds prediction scoring **and** velocity-based learning) | Live |
| `competitor_discover` | daily 06:30 | Find new competitor channels | Live |
| `competitor_intel` | daily 07:00 | Rebuild competitor profiles/benchmarks (delete-all-then-rebuild-all each run) | Live |
| `learning` | daily 02:00 | Build channel style/performance profile — **prefers true first-24h velocity** (nearest T+24h snapshot), falls back to the cumulative views/age proxy per post | Live |
| `growth_detection` | daily **05:30** | Build growth strategy + recommendations. Runs **before** `daily_plan` so the plan grounds on a fresh blueprint | Live |
| `daily_report` | daily 05:15 | Persist `daily_channel_reports` | Live |
| `daily_plan` | daily **06:00** | Generate today's **AI daily plan** (per-post slots: window/type/theme/merchant) via `ensure_daily_ai_plan`. **No longer pre-renders drafts** — slots are filled just-in-time | Live |
| `jit_fill` | 1 min | For each AI-plan slot due within a 3-min lookahead: scrape the live pool, pick a fresh item matching theme/merchant (broadens + logs on miss), AI-write the post (template fallback), write `generated_posts` + enqueue. Idempotent per slot | Live |
| `ai_daily_summary` | daily 08:00 | Groq daily briefing (text only, not stored) | Live |
| `weekly_report` | Mon 08:30 | Deterministic weekly plan (`CampaignPlanningEngine`) + **AI weekly plan** (`generate_week_plan` → persisted as the WEEKLY `campaign_plans` row the daily planner reads) + Groq weekly briefing | Live |
| `weekly_retro` | Mon 07:30 | Compare last week's predictions vs actuals (before `weekly_report`) | Live |
| `queue_processor` | 1 min | Publish due `scheduled_posts` | Live (send gated on admin rights + sign-off) |
| `notification_engine` | 5 min | Flag blocked posts / failed runs | Live |
| `org_health` | 1 h | Check config completeness | Live |
| `url_health` | 12 h | Sweep `enriched_deals` for dead links | Live |
| `analytics_aggregation` | 1 h | Aggregate analytics data | Live |
| `deal_expiry` | 1 h | Mark expired deals invalid | Live |
| `db_cleanup` | daily 03:00 | Delete old `scheduler_runs`/`collection_events` (+ 90-day competitor-intel prune) | Live |
| `deal_monitoring`, `price_history` | 2h / 6h | Stock / price checks | **Stub — always returns "limited"** |
| `monthly_report` | 1st @ 00:05 | 30-day post count | **Placeholder, no dedicated table** |

**Why the stubs/placeholder are still registered (not deleted):** `deal_monitoring` and `price_history` need per-merchant price/stock scraping, which is blocked or has no API for most merchants today (see the `merchants` registry) — so they return an honest `"limited"` instead of fabricating stock/price data. `monthly_report` has no dedicated rollup table yet. They're kept in the registry on purpose: each **reserves its cadence slot**, still writes a `SchedulerRun` audit row every run (so the pipeline is complete and observable), and **lights up automatically** the moment the missing capability (merchant scraping / a monthly table) lands — no scheduler rewiring needed. A visible `"limited"` beats a silent gap.

There's also a **legacy, unused** `CollectionScheduler` (`services/collection/scheduler.py`) that reads the old `OWNED_INCREMENTAL_INTERVAL_MIN`-style env vars — only reachable via `cli.py`, not wired into the app. Not part of the live system.

### Why it runs in this order (and at these cadences)

The clock times aren't arbitrary — the daily jobs form a strict **producer → consumer chain**, and each one is timed to run *after* whatever it depends on has finished. Rationale lives in `controllers/cadences.py`; the load-bearing points:

**The daily chain (each step feeds the next):**
1. `learning` **02:00** — rebuilds "what's working" from yesterday's *fully-matured* post metrics. Runs in the quiet early morning so the heavy full-history scan is done long before planning.
2. `daily_report` **05:15** — persists yesterday's aggregates (the AI's main data diet).
3. `growth_detection` **05:30** — turns learning + reports into the strategy *blueprint*. Deliberately moved to run **before** the plan — it used to run after, so the plan grounded on a day-old blueprint.
4. `daily_plan` **06:00** — the AI planner is only as good as the blueprint + report beneath it, so it runs **last** in the chain.
5. `jit_fill` **every 1 min** — executes the plan just-in-time, filling each slot ~3 min before it fires, so post content is scraped fresh at fire-time instead of pre-rendered hours stale.
6. `queue_processor` **every 1 min** — publishes due posts (gated).

**Two more ordering constraints that MUST hold:**
- `competitor_discover` **06:30** → `competitor_intel` **07:00** — newly found channels must be *collected* before they're *profiled* (else same-tick profiling sees no posts).
- `weekly_retro` Mon **07:30** → `weekly_report` Mon **08:30** — the report/plan must read a *fresh* retro.

**Why the cadences fall into three tiers:**
- **Near-real-time (1–5 min)** — `telegram_sync`, `normalize_posts`, `jit_fill`, `queue_processor`: freshness-critical. A slot must fill and fire on time, and new posts must be captured before their view-velocity signal decays.
- **Periodic (10–30 min)** — competitor sync, stats refresh, link resolution, merchant feed, deal ranking, outcome collector: useful but not minute-sensitive; batched to limit load on Telegram / merchant sites / our DB.
- **Daily / weekly / monthly** — learning, growth, intel, reports, retros: expensive *delete-all-then-rebuild-per-version* recomputes that only need to reflect a day's or week's change; running them more often would burn compute for no fresher signal.

> **Don't reshuffle times blindly.** These dependencies (`learning → growth → daily_plan`, `daily_report → daily_plan`, `discover → intel`, `retro → weekly_report`, and `jit_fill` only after a plan exists) are encoded *only* by the staggered clock times. Move a time and you can silently feed a stale input downstream — nothing enforces the order at runtime.

---

## 5. AI layer — how Groq gets used

```mermaid
flowchart LR
    DB[("DB: reports, profiles,\nstrategies, insights, deals")] --> CTX["context.py\n(read-only, no LLM)"]
    CTX --> CLIENT["AIClient\n(Groq, llama-3.3-70b)"]
    CLIENT --> PLANNER["planner.py\ngenerate_day_plan()\ngenerate_week_plan()"]
    CLIENT --> BRIEF["briefing.py\ndaily/weekly briefing"]
    CLIENT --> COACH["coach.py\nGrowthCoach (agentic Q&A)"]
    CLIENT --> COPY["copywriter.py\nwrite_for_item()"]
    PLANNER --> FC["factcheck.py\n(deterministic, no LLM)\nverifies every cited number"]
    FC --> CPLAN[("campaign_plans")]
    BRIEF --> TXT["text only\n(not persisted)"]
    COACH --> TXT
    CPLAN --> JIT["jit_fill\n(reads plan slots +\nfresh scraped deals)"]
    FRESH[("live deal pool")] --> JIT
    JIT --> COPY
    COPY --> GP[("generated_posts")]
```

- **Every AI call is grounded** — `context.py` builds the JSON bundle from real DB rows first; the LLM never sees free-form access to the database.
- **Fact-checking is deterministic**, not AI: `factcheck.py` checks every number the planner cited against `daily_channel_reports` (2% tolerance) before the plan is marked trustworthy.
- **The planner persists output and it drives scheduling.** `campaign_plans` holds both the AI **daily** plan (per-day, cached per day — see `daily_brief()`/`ensure_daily_ai_plan()`) and the AI **weekly** plan (`generate_week_plan`, persisted Mon 08:30 and read back by the daily planner as `this_week_theme`/`this_week_direction`). The daily plan's `post_slots` are the **source of truth** the `jit_fill` worker executes — no longer a dashboard-only artifact. Briefing and coach answers are request/log-only, not stored.
- **Every AI call uses a real system prompt.** `AIClient.complete()` puts `GROUNDING_SYSTEM` + the call's instruction block in the *system* role. The planner, briefing, coach and copywriter all pass their instructions via `system_extra=` (the briefing previously smuggled them into the user message — fixed).
- **Scheduled draft text is AI-first with a deterministic fallback.** `jit_fill` calls `Copywriter.write_for_item()` — it hands the model the slot's freshly-scraped deal plus the org's saved deal/loot **post template as the "winning-format" exemplar** — and only if the AI is unavailable does it fall back to `PostFormatter` template rendering. The post-text templates are **editable** and live in `organizations.settings["post_templates"]` (seeded from code defaults; safe-rendered so a bad edit can never crash generation). The older fully-deterministic engines (`engine.py`) still back the opt-in `/run/generate-live` path.
- `insight_writer.narrate()` is a small AI-assist used *inside* the Growth/Reasoning engines to phrase a "why" sentence from evidence — always has a deterministic fallback string if AI is unavailable.
- **The planner degrades gracefully without AI.** When Groq is unavailable (`ai_available:false`), `/plan/daily` still returns a full deterministic plan — `posting_windows`, `deal_type_allocation`, and `merchant_allocation` are computed by `CampaignPlanningEngine` from real history (see §7 note on cold-start fallbacks). Only the free-text digest / AI-only slots go empty, and `jit_fill` falls back to template-rendered copy.

---

## 6. From data to dashboard

| Page | Endpoint | Reads |
|---|---|---|
| Overview (`/`) | `/overview`, `/growth`, `/competitor-dashboard`, `/insights`, `/drafts`, `/queue` | `daily_channel_reports`, `daily_subscriber_stats`, competitor profiles, `reasoned_insights` |
| `/analytics` | `/analytics` | `posts`+`normalized_posts` (hour/weekday/type/merchant totals, **posts-per-hour count chart** from `by_hour[].n`, golden hours), `daily_subscriber_stats` (growth) |
| `/day` | `/day` | `posts`+`normalized_posts`+`merchants` for a date or range |
| `/competitors` | `/competitor-dashboard`, `/competitor-dashboard/trends` | `competitor_profiles`/`benchmarks` (ranking, merchant coverage/share, weekday/hour heatmaps) plus day-bucketed posts/views trend across all competitors, computed on demand from `competitor_posts` |
| `/competitors/[id]` | `/competitors/{id}/trends` | Per-competitor deep dive: top posts, content mix, media-vs-text, link usage, caption-length distribution, posting consistency — day-bucketed reads of `competitor_posts`/`normalized_posts`, computed on demand (not persisted) |
| `/plan` | `/plan/daily`, `/plan/weekly` | `campaign_plans` (AI planner + briefing; weekly is keyed to a real IST calendar week and only calls the AI once per week, reusing the cached digest otherwise). Deterministic `posting_windows` / `deal_type_allocation` are computed by `CampaignPlanningEngine` and fall back to owned history when the growth blueprint is cold (§7). |
| `/drafts` | `/drafts` | `generated_posts` |
| `/queue` | `/queue` | `scheduled_posts` |
| `/settings` | `/org`, `/users`, `/channels`, `/competitors` (GET + POST) | `organizations`, `users`, `channels`, `competitors` — the Competitors tab lists/adds competitors (Direct/Indirect); the **Post Templates** tab (owner-only) reads/writes `organizations.settings["post_templates"]` via `PATCH /org` (partial merge) |

No page currently reads `scheduler_runs` — there's no Schedulers status page/router yet, even though the audit table exists.

---

## 7. Code map — where things live (for agents)

Backend rooted at `be/`, frontend at `next/`. Only the load-bearing files are listed; use these as jump-off points.

### Backend (`be/src/`)

| Area | File(s) | What's there |
|---|---|---|
| **HTTP routes** | `routers/` (8 modules) | `data.py` (analytics/day/plan/competitors/drafts/queue + the bulk of GETs), `auth.py`, `users.py`, `channels.py`, `org.py`, `control.py` (`POST /run/pipeline`, `/run/generate-live`), `health.py`. Every response is the envelope `{success, data, error}` via `ok(...)`. |
| **Request-time orchestration** | `controllers/service.py` (~1.5k lines) | The workhorse: `daily_brief()`, `_today_details()`, `weekly` plan assembly, overview/competitor dashboards. Most `/data` routes call into here. |
| | `controllers/jobs.py` | `JobManager` — in-process pipeline/generate-live triggers behind `/run/*`. |
| | `controllers/schedulers.py` | All cron jobs (APScheduler, IST). Off unless `SCHEDULERS_AUTOSTART=true`. |
| | `controllers/accounts.py` | Org/user CRUD. `_EDITABLE_SETTINGS` allow-lists which `org.settings` keys `PATCH /org` may write (includes `post_templates`). |
| **Planning** | `services/planning/campaign.py` | `CampaignPlanningEngine`: `_recent_distribution` (owned 45-day merchant/deal-type counts), `_allocate_posts`/`_allocate_from_recent` (single vs loot mix — cold-start now derives the split from the Growth blueprint's competitor `content_mix_reference`, 60/40 only as last resort), `_recent_hourly_all`/`_recent_posting_windows` (posting-window fallback), `_daily_plan`, `_weekly_plan`, `_risks`. |
| | `services/planning/posting_windows.py` | Shared pure `build_posting_plan(posts_per_day, hourly_all)` + `DAY_PARTS`. Reused by both `campaign.py` and `intelligence/growth.py` (single source of truth for day-part distribution). |
| **Generation** | `services/generation/jit_fill.py` | **`fill_due_slots()`** — the just-in-time executor and the real posting path. Reads AI-plan `post_slots` due within a 3-min lookahead, scrapes the live pool, matches each slot's theme/merchant (`exact → theme → any` broadening, logged), AI-writes via `Copywriter.write_for_item` (template fallback), writes `generated_posts` + enqueues + a baseline `PostPrediction`. Idempotent per slot (`selection_bucket` tag). Has a `_selfcheck()`. |
| | `services/generation/daily_planner.py` | **Retired** deterministic planner — only the `recently_used_urls()` 3-day dedup helper survives; the old `build_and_schedule_day()` was replaced by `jit_fill`. |
| | `services/generation/formatting.py` | `PostFormatter` — deterministic post text (fallback path + `/run/generate-live`). `DEFAULT_POST_TEMPLATES`, safe `_render()` (falls back to default on any bad template). |
| | `services/generation/engine.py` | `PostGenerationEngine`, `LiveDealGenerationEngine` (groups today's fresh deals by category), `ObservedPostGenerationEngine`. Pass `org.settings["post_templates"]` into `PostFormatter`. |
| | `services/generation/deal_source.py` | `DealSourceClient` — live GrabCash feed (reads `DEAL_API_BASE`). |
| | `services/affiliate/grabon.py` | `GrabOnAffiliateProvider` — Amazon/Flipkart affiliate params + `grbn.in` shortening. |
| **Collection** | `services/collection/link_resolution.py` | `LinkResolutionEngine` — shortlink → merchant, incl. meta-refresh/JS follow (`_extract_html_redirect`, `_resolve_one`). |
| | `services/collection/merchants/registry.py` | `MERCHANT_SEED`, `detect_merchant_key()` — the known-domain list. |
| **Processing** | `services/processing/normalizer.py` | `PostNormalizer` — raw post → `normalized_posts` (merchant only from known domains; shortlink resolution is the later link-resolution pass). |
| **Analytics** | `services/analytics/views.py` | `compute()` — the `/analytics` payload (`by_hour[].n`, `golden_hours`, etc.); `_owned_rows()` + `to_ist()` are the canonical owned-post/hour source. |
| | `services/analytics/day.py`, `comparison.py`, `competitor_trends.py` | `/day` summary, us-vs-competitor comparison, per-competitor trends. |
| **Intelligence** | `services/intelligence/growth.py` | `GrowthEngine` — growth blueprint incl. `posting_plan` (via `build_posting_plan`), content-mix. |
| **AI** | `ai/context.py` | Read-only DB→JSON bundlers (grounding). `ai/planner.py` (`generate_day_plan` + `generate_week_plan`), `briefing.py`, `coach.py`, `copywriter.py` (`write_for_item` fill-time + `write_for_deal` CLI), `factcheck.py`, `insight_writer.py`, `client.py` (Groq — `complete()` takes `system_extra`). Prompts in `ai/prompts/`. |
| **Learning** | `services/learning/channel_learning.py` | `ChannelLearningEngine` — `Fact.view_rate()` prefers true first-24h velocity (nearest T+24h `post_metric_snapshots`) over the cumulative views/age proxy; emits `channel_style_profiles`/`post_type_performance`/`learning_records`. |
| **DB** | `db/models*.py` | ORM split across `models.py` + `models_*.py` by domain. `db/base.py` = `Base`. |
| | `db/migrate.py` | `add_missing_columns(engine)` — the additive-column patcher (**no Alembic**; see §8). |
| | `db/session.py` | `get_engine()`/`get_sessionmaker()` (lru_cache), `session_scope()`. |
| | `db/org_seed.py` | Seeds the default org/user/channels + `post_templates` defaults; DB-wins merge on startup. |
| **Scripts** | `scripts/collect_data.py` | The big CLI ingest/backtest tool (`--initial`, `--backtest`, `--days-back`, `--skip-*`, `--link-resolve-limit`, …). |
| | `scripts/reset_db.py` | Wipe operational data, keep org/users/channels/competitors. Dry-run unless `--yes`. |

### Frontend (`next/`)

| Area | File(s) | What's there |
|---|---|---|
| Pages | `app/(dashboard)/<route>/page.tsx` | `analytics`, `day`, `plan`, `competitors`, `competitors/[id]`, `drafts`, `queue`, `settings/*` (incl. `settings/templates`). |
| Data layer | `queries/queries.ts` (GET hooks), `queries/mutations.ts` (writes), `queries/keys.ts` (query keys) | React Query. `useOrg`/`useUpdateOrg` back the templates editor. |
| API client | `services/api.ts` | `get/post/patch/put/del`; unwraps the `{success,data,error}` envelope. |
| Types | `types/api.ts` | Mirrors backend payloads (`DailyPlanToday`, `PostingWindowRow`, `PostTemplates`, `MetricBucket`, …). |
| Charts | `components/*Chart*`, `settings/settings-nav.ts` | `BarsChart`/`MultiLineChart`/`HeatStrip`; settings nav registration. |

---

## 8. Conventions & gotchas (read before editing)

- **No Alembic.** Schema = `Base.metadata.create_all()` + the hand-written additive patcher `db/migrate.py:add_missing_columns()`. `create_all()` only creates missing *tables*, never ALTERs existing ones — so any new model column must be added to `migrate.py`'s `_ADDITIONS`. This also applies to the dated export `.db` files (`collect_data.py` runs the patcher on them too).
- **Envelope everywhere.** Backend returns `{success, data, error}`; the FE `api` service unwraps `data`. Don't return bare objects from routes.
- **Schedulers off by default** (`SCHEDULERS_AUTOSTART=false`). Nothing ingests/plans automatically in dev — trigger via `scripts/collect_data.py` or the `/run/*` endpoints.
- **Cold-start fallbacks (tiered, not a magic constant).** The plan must never come back empty just because Growth/learning hasn't run. `deal_type_allocation` falls back in order: owned recent single/loot split → the Growth cold-start blueprint's competitor-derived `content_mix_reference` (`{single_deal/loot_deal}` counts over comparable channels) → a neutral 60/40 single/loot default **only** when there's no owned history *and* no usable competitors. `posting_windows` falls back to `_recent_posting_windows` (owned hour distribution weighted by views, same `_owned_rows` source as the analytics chart). Only override these fallbacks when a real growth blueprint is present.
- **Editable templates are safe by construction.** `PostFormatter._render()` catches template errors and falls back to `DEFAULT_POST_TEMPLATES`. When adding a new template string, add its default there and document its placeholders.
- **SQLite pragmas** (`db/session.py`): `foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout=5000` on every connection.
- **Sync SQLAlchemy 2.0** throughout — use `session_scope()`; engines/sessionmakers are `lru_cache`d.
- **IST is the product timezone.** Analytics/schedulers bucket by IST via `to_ist()`; timestamps in the DB are UTC.
