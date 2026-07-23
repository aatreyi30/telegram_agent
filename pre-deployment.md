# DealWing — Pre-Deployment Notes

_Branch `jk/rewamp/loop` · compiled 2026-07-23 · deploy mode: **manual run, no Docker (for now)**_

This is the go/no-go sheet before running the agent live. It covers (1) how the
manual run boots, (2) the Docker state (validated, unused for now), and (3) the
open concerns from the end-to-end review, ranked by whether they can silently
stop the pull → plan → post → analytics loop.

---

## 0. The one safety rule that must hold

**`PUBLISH_CHANNEL` is the only channel auto-send will ever post to.**
- Leave it **blank** → every post is planned, written, and queued but **nothing leaves**. Safe default.
- Set it to the **test channel** (`@demotestchanneljk` / `-1004473913412`) → real output lands there for review.
- Only set it to the live channel (`@GrabOnIndiaOfficial`) when every planned post should go public.

Admin rights alone never cause a post. Gate 1 = `PUBLISH_CHANNEL` match; Gate 2 = live `post_messages` rights check. Both must pass. **Real posting to the live channel stays the operator's manual job.**

---

## 1. Manual run (the mode we're deploying in)

```bash
cd be
python -m venv .venv && . .venv/Scripts/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # then fill it in (see §4)

python -m src.cli init-db                             # tables + merchant seed + org/admin (idempotent)
python -m src.cli telegram-login                      # once, interactive (phone + code) — writes the .session file
python -m src.cli doctor                              # confirms which data sources are actually reachable

# serve the API + dashboard
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1
```

- **One worker only.** The cron scheduler holds a cross-process leader lock; a second worker is not a second scheduler, but keep it to `--workers 1` to avoid surprises.
- `src/main.py` `_lifespan` re-seeds org/admin on every boot (idempotent) so a fresh deploy can log in.
- **Scheduler autostart is OFF by default** (`SCHEDULERS_AUTOSTART=false`). In manual mode you drive the cron yourself:
  - `python -m src.cli run-scheduler` → lists all jobs
  - `python -m src.cli run-scheduler <key>` → run one job once (wire these into Windows Task Scheduler / OS cron), **or**
  - set `SCHEDULERS_AUTOSTART=true` to let the single uvicorn process run all 20 cron jobs itself (fine because it's a single container/process).

---

## 2. Docker — checked, valid, ready, currently unused

Verified this session:
- `docker --version` → **29.5.2** installed.
- `docker compose config` → **parses clean**, context `./be`, Dockerfile `be/Dockerfile`, binds `./be/data` → `/app/data` for DB + raw-snapshot persistence.
- `be/Dockerfile` is sound: python:3.12-slim, deps-first layer caching, `--workers 1` (correct for the leader lock), `$PORT` expands at runtime (Render/Railway), falls back to 8000.
- `render.yaml` is a complete blueprint (single web service, docker runtime, 1GB persistent disk at `/app/data`, all secrets `sync: false`).

**Gaps to know before you ever `docker compose up`:**
- `docker-compose.yml` passes **no** Telegram/AI/deal-API env and **no** `.env` file — it's a bare local smoke harness, not a real run. For a real container you'd add `env_file: ./be/.env` (or the `-e` vars) and drop the `.session` file into the mounted `./be/data`.
- `telegram-login` is interactive → **cannot** run inside the container. You log in on the host, then mount the resulting `.session` into `/app/data` (render.yaml already expects `TELEGRAM_SESSION_NAME=/app/data/growth_agent`).
- Frontend is **not** dockerized — build `fe/dist` (or run Next separately) and point it at the backend.

**Verdict: Docker is deployment-ready but we're not using it yet — nothing blocking. The manual run above is the supported path for now.**

---

## 3. Open concerns from the end-to-end review

Ranked by blast radius. **Tier 1 = can silently kill the pull-and-post loop** (nothing crashes, nothing posts, no error surfaced). None of these are fixed yet.

### Tier 1 — silent-failure, decides whether it reliably posts for 5 days

| # | Concern | Where | What actually happens | Fix |
|---|---------|-------|----------------------|-----|
| 1 | **Goes dark when AI is down** | `jit_fill.py:256` | The factcheck allowlist is `("passed","warn","skipped","")` — it **excludes `"fallback"`**. When the AI provider is down and copy falls back to the deterministic writer, the post is marked `fallback` and **rejected**, so the slot fires nothing. One AI outage = a silent posting gap. | Add `"fallback"` to the allowlist (one word). Restores AI-outage resilience. |
| 2 | **A loot board dies on one bad deal** | `publishing.py:90–95`, `revalidate.py:145–149` | Revalidation returns on the **first** failing deal, and publishing blocks the **whole** post if any single deal in a loot fails. One stale/out-of-stock item in a 10-deal board kills the entire board. | Drop the failed deal, publish the board if ≥N deals survive; only block if the board falls below a floor. |
| 3 | **Feed collapses to one merchant (schema drift)** | `deal_scraper.py:46–54` | `is_relevant` checks `ALLOWED_MERCHANTS` against the **raw** `retailer_key` **before** `_map_item` aliases it. GrabCash uses compound keys (`nykaa_fashion`, likely `amazon_in`) → they don't exact-match `"amazon"` and are **silently dropped**. Live evidence: 100% of enriched deals were `ajio`; zero amazon/flipkart/myntra survived the gate. | Normalize `retailer_key` (strip `_in`/`_fashion` suffixes or match by prefix) in the shared `filter_relevant` gate so every consumer is covered at once. |
| 4 | **A post can go out with no link** | `copywriter.py:121–133`, `assemble_loot:136–162` | No assertion that a product/affiliate link is actually present in the assembled post. A malformed deal → a linkless post that earns ₹0 and looks broken. | Assert a link is present before the post is publishable; skip the deal if not. |
| 5 | **Over-/under-posts when clamping counts** | `ai_execution.py:35`, `jit_fill.py:67` | `_rescale_slot_counts` can round a slot to `count=0`; `_expand_slots` then revives `0→1` (`max(1, …)`). Result: when the planner scales the day **down**, zeroed slots come back to life and it **over-posts**. | Skip `count<=0` in `_expand_slots` instead of reviving it. |

### Tier 2 — real but narrower (crash / edge windows)

| # | Concern | Where | What happens | Fix |
|---|---------|-------|--------------|-----|
| 6 | **Crash mid-send can double-post** | idempotency via `selection_bucket` tag, **no DB unique constraint** | Dedup relies on the cron file-lock + a tag, not a DB constraint. A crash between send and status-write could re-fire the same slot. | Add a unique index/column on `(selection_bucket, …)`. **Needs a schema migration → follow-up, not a blocker for a supervised run.** |
| — | Stale-`SENDING` reclaim window | `scheduler.py:71–85` (`_reclaim_stale_sending`) | A row stuck in `SENDING` (killed process) is reclaimed on a timer — correct, but confirm the timeout is shorter than the poll so it actually retries. | Verify the reclaim timeout vs poll interval. |

### Tier 3 — cosmetic / analytics accuracy (won't stop posting)

| # | Concern | Where | What happens | Fix |
|---|---------|-------|--------------|-----|
| 7 | **Dashboard empty until `normalize` runs** | `day.py:43,64`, `views.py` | Analytics/day views **inner-join** `NormalizedPost`, which is written **only** by `processing/normalizer.py`. Until `normalize` runs, the dashboard reads empty even though posts exist. | Run `normalize` in the cron chain before analytics (the `pipeline` command already does); or LEFT-join. |
| 8 | **Growth date-range off-by-one** | `growth.py:77,91` | The range end excludes the last day, so day-over-day growth can miss the most recent day's delta. Doesn't corrupt telescoping, just trims the window. | Make the range end inclusive. |

**What the review confirmed is sound (not concerns):** wrong-channel posting is impossible with the gates; the new price-band/tier loot code is correct; cold-start is safe (neutral 60/40 mix, never empty); no double-post under normal operation; growth telescopes correctly over 5 days once §8 is addressed.

---

## 4. Pre-flight checklist

- [ ] `.env` filled — `TELEGRAM_API_ID/HASH/PHONE`, `OWNED_CHANNELS`, `OPENAI_API_KEY` (or `GROQ_API_KEY`), `DEAL_API_BASE` + auth, `AUTH_SECRET`/`ADMIN_*` changed off `change-me`.
- [ ] `PUBLISH_CHANNEL` = **blank or test channel** for the first live days (see §0).
- [ ] `python -m src.cli init-db` run; `python -m src.cli telegram-login` done; `.session` file present.
- [ ] `python -m src.cli doctor` shows Telegram + deal source **available** (not "unavailable").
- [ ] `python -m src.cli fetch-deals` returns a **merchant mix**, not 100% ajio — if it's all ajio, **Tier 1 #3 is biting**, fix before trusting earnings.
- [ ] Decide cron: `SCHEDULERS_AUTOSTART=true` (in-process) **or** OS-scheduled `run-scheduler <key>` calls.
- [ ] `pytest` green (last run: **319 passed**).

## 5. Recommendation

**Safe to deploy in supervised mode now** — with `PUBLISH_CHANNEL` on the test channel, the loop pulls, plans, writes, and queues without risk to the live channel. Before pointing it at the live channel for an unsupervised multi-day run, land **Tier 1 (#1–#5)** — those are the ones that go dark without telling you. #1 and #5 are one-line fixes; #3 is the one that decides whether posts actually earn. Tier 2 #6 and Tier 3 can follow after.
