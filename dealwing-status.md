# DealWing — status & open issues

> **⚠️ SUPERSEDED (2026-07-21).** The "PENDING — feed & affiliate" section below is
> RESOLVED: sourcing moved to the GrabCash export API (per-retailer, images, Myntra now
> included), the planner posts a real loot+single mix, and Amazon/Flipkart/**Myntra**
> affiliate rules earn (config is DB-backed in `org.settings`). Ajio still has no rule.
> See **`data_flow.md` §9** for the full resolution log. Kept below for history.

_Last updated: 2026-07-18 · branch `jk/rewamp/loop`_

Working log of the three workstreams from this session. **UI revamp** and **post
variety** are done and verified; **feed & affiliate (GrabCash / "everything earns ₹0")**
is the big open one, blocked on the deals API being reachable.

---

## ✅ Done — 1. Post variety (posts no longer look like one template)

**Problem:** every single-deal post was the same 6-block skeleton (`hook / name /
discount / price / coupon / cta`, always `\n\n` apart). Different words, identical shape.

**Fix:** a rotating set of **post styles**, each pairing a tone/emoji directive (varies
the words) with a layout (varies the shape/spacing). `jit_fill` cycles a counter so
consecutive posts never share a style. Link-swap safety + "real numbers only" guardrails
untouched — the model still only writes safe tagged sections.

| Style | Voice | Shape |
|---|---|---|
| classic | urgency 🔥 | every block separate |
| compact | punchy ⚡ | discount + price on one line |
| curious | question hook, clean | name + discount as a headline |
| value | warm 💰 | dense single-line spacing |
| bold | playful 🤑 | discount-led, no hook |

Loot boards get a parallel rotation of 4 banner flavours (Mega-loot / Steal-alert /
Seasonal / Curated).

**Files:** `be/src/ai/post_styles.py` (new) · `be/src/ai/copywriter.py` (layout-driven
assembly + `variant`) · `be/src/services/generation/jit_fill.py` (rotation counters).
**Verified:** self-checks pass; live runs against gpt-4o-mini show real variety across
two products.

---

## ✅ Done — 2. UI revamp (a marketing operator's command center)

**Foundation (shared layer, kills the same rot on every page):**
- `next/lib/format.ts` — humanizers (`single_deal`→"Single deal", `nykaa_fashion`→"Nykaa
  Fashion", `blocked_stale`→"Stale link"), IST time + "fires in 12 min", honest money logic.
- Components: `PostPreview` (renders the real Telegram post — bold, live links),
  `StatusPill` + `StatusCounts`, `MoneyBadge`, `PageHeader`.

| Page | What changed |
|---|---|
| Queue | Rebuilt — click a row → real post in a drawer; `Single deal · AJIO` chips not `aislot:5:1:0`; IST relative time; honest status. |
| Drafts | Green "affiliate links" **lie killed** → honest Earns / Shortened-only chip; renders bold. |
| Overview | Fixed "shows 1 draft when you have 50" (`page_size=1` count bug); plain-word queue statuses; publishing readiness shows the real failure reason. |
| Plan | Killed the permanent "N more needed" (under JIT the plan's **slots are** the schedule); retro de-jargoned (MAPE→"Avg forecast error"); keys humanized. |
| Analytics / Day | Every chart label humanized (post types, merchants). |
| Competitors | Chart labels humanized; faked "Processing" badge → honest "No posts in range"; IST trend dates. |
| System health (was "Jobs") | Reframed for a human — "All systems fresh / N need attention", plain status, stack traces hidden behind hover. |
| Settings | Users: delete confirms, can't demote/delete self, create validated. Channels/Competitors: plain status, no more "@null", "Last collected" column, monitoring failures surface. Org: plain-language hints on affiliate fields. |

**Backend:** queue endpoint now sends post text + merchant + type (`be/src/controllers/
service.py`, `_post_facts`); `jit_fill` stamps `primary_merchant`.
**Verified:** `tsc` clean, `next lint` clean.

⚠️ **Queue/Drafts need a backend restart** to serve the new payload fields.

---

## ✅ Done — 3. Cleanup / dead code

**Removed:** `billing/page.tsx` (fake page, not linked); scratch md files; `usePlans` +
`useWeekly` hooks and their dead type chains (`PlansResponse`, `CampaignPlanDTO`,
`DailyPlanBlueprint`, `EventPlanBlueprint`, `DealTypeAllocation`, `WeeklyResponse`,
`WeeklyPlanBlueprint`, `DailyThemeRow`); unused `format.ts` helpers (`pct`, `compact`,
`istTime`, `istWeekday`).
**DRY:** `StatusCounts` component (was copy-pasted 3×), `atOr()` helper (dup in 2 dialogs).

**Flagged but deliberately kept** — API-contract type fields the backend actually returns
but the UI doesn't show yet: `SchedulerRunsResponse.runs`, `SchedulerJobStatus.
last_duration_ms`, `OverviewResponse.affiliate_provider`, `AnalyticsWindow.source`, and
the hidden `CompetitorEntity` metrics (`cta_rate`, `coupon_rate`, `similarity_to_us`, …).
These are *data*, not dead code — surface them or drop from the payload, don't just trim
the type.

---

## ⛔ PENDING — 4. Feed & affiliate (GrabCash) — the money problem

**Every post that goes out currently earns ₹0.** Two independent bugs, both real:

### 4a. The feed collapses to AJIO
- The relevance gate `ALLOWED_MERCHANTS = {"amazon","flipkart","myntra","ajio"}` in
  `be/src/services/collection/deal_scraper.py` uses an **exact** membership check
  (`str(it["retailer_key"]).lower() not in ALLOWED_MERCHANTS`).
- The GrabCash feed uses **compound keys** — we saw `nykaa_fashion` live. If amazon
  arrives as `amazon_in` (the same pattern), it is **silently dropped** even though amazon
  is "allowed."
- Evidence: `enriched_deals.merchant_key` in the DB = **`['ajio']`** (100% ajio, every
  post ever). A live feed sample was nykaa_fashion 52 · ajio 42 · shopsy 11 · tatacliq 9 ·
  nykaa 6 — **zero** amazon/flipkart/myntra survived the gate.
- **Unverified:** the exact `retailer_key` string amazon arrives as. The deals API is
  Cloudflare-blocking both the direct call and the Camoufox fallback right now, so this
  couldn't be confirmed live.

### 4b. AJIO (and myntra) earn nothing
- `build_affiliate_url` in `be/src/services/affiliate/grabon.py` has real affiliate rules
  for **only amazon (tag) and flipkart (affid params)**. ajio/myntra return `None` →
  `_finalize_link` (`be/src/services/generation/formatting.py:157`) falls back to a **clean
  URL that is merely shortened** (grbn.in) — no commission.
- So the feed is ~100% ajio (4a) and ajio has no affiliate rule → **every posted deal
  earns ₹0**, while `format_meta.affiliate_status` is still stamped `grabon_applied`
  (misleading). *The UI now tells the truth* (MoneyBadge shows "Shortened only"), but the
  underlying earning gap is unfixed.

### Fix plan (when the feed is reachable)
1. **Re-probe the live feed** unfiltered and record the exact `retailer_key` strings for
   amazon/flipkart/myntra (confirm they even appear, and under what key).
2. **Make the merchant gate robust** — normalize `retailer_key` before the `ALLOWED_MERCHANTS`
   check (strip suffixes like `_in`/`_fashion`, or match by prefix) so `amazon_in` counts as
   amazon. Shared gate in `deal_scraper.filter_relevant` covers every consumer at once.
3. **Close the earning gap** — either expand `build_affiliate_url` with rules for the
   merchants the feed actually delivers, or restrict `ALLOWED_MERCHANTS` to only merchants
   that have an affiliate rule (post only what earns). Decide product-side.
4. Stop stamping `grabon_applied` when the link was only shortened (make `affiliate_status`
   honest at the source, not just in the UI).

---

## Other open items
- **Surface the kept competitor metrics** (4-tile: CTA rate / coupon rate / similarity /
  posting cadence) on the Competitors page — data already computed, currently hidden.
- **Full pytest suite** not run this session (had ~9 pre-existing failures unrelated to
  these changes; targeted self-checks were run instead).
- **Deals API** is Cloudflare-blocked from this environment (direct 403 → Camoufox 403),
  which is what blocks verifying 4a. Needs to be run from a context that can reach it.
