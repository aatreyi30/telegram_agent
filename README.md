# DealWing — Telegram Deal-Channel Growth OS

DealWing learns from your Telegram deal channel and your competitors, turns that into
strategy‑compliant post drafts and plain‑language recommendations, and shows honest
analytics — every number labelled with the time window and sample it came from.

Two independent apps live side by side (not a monorepo):

- **`be/`** — FastAPI backend: the intelligence engines, a JSON API, auth, and a CLI.
- **`fe/`** — Vite + React + shadcn/ui frontend: landing page, login, and dashboard.

Each installs and runs on its own; the backend can also host the built frontend.

---

## Features

- **Strategy‑compliant generation** — drafts follow the learned strategy (right post
  types, right emojis, real affiliate links), and each draft explains *why*.
- **Explainable insights** — every recommendation shows the calculation, evidence, and
  the period + sample behind it.
- **Honest analytics** — views by day / hour (IST) / weekday / post‑type / merchant, with
  a date‑range filter and a per‑day "what happened" view.
- **Agentic pipeline** — one action runs normalize → classify → intel → learn → growth →
  reason → plan → AI briefing (start/stop from the UI).
- **Multi‑user auth** — accounts with roles (owner / editor / viewer); org + user settings.
- **Standard API envelope** — every response is `{ success, data, error }`; docs at `/api/docs`.

---

## Project structure

```
.
├── be/                       # FastAPI backend
│   └── src/
│       ├── main.py             # app assembly + entry (uvicorn src.main:app)
│       ├── cli.py              # Typer CLI (python -m src.cli …)
│       ├── config/  logger/    # settings (env-driven) · logging
│       ├── shared/             # { success, data, error } envelope + auth deps
│       ├── middleware/         # error handlers
│       ├── routers/            # HTTP routes (health, auth, data, control, channels, users, org)
│       ├── controllers/        # request logic (service, accounts, jobs)
│       ├── services/           # domain engines (collection, intelligence, generation, analytics, …)
│       └── ai/  auth/  db/     # LLM layer · auth (pbkdf2/HMAC) · SQLAlchemy models + session
│   ├── tests/
│   ├── Dockerfile  pyproject.toml  requirements*.txt  .env.example
├── fe/                       # Vite + React + shadcn/ui
│   └── src/{routes, features, components/ui, providers, services, hooks, lib, constants, types, styles}
├── docker-compose.yml        # runs the backend container
└── README.md
```

---

## Getting started

### Backend (`be/`)

```bash
cd be
python -m venv .venv
.venv\Scripts\activate         # Windows   (source .venv/bin/activate on macOS/Linux)
pip install -r requirements-dev.txt
cp .env.example .env           # fill in secrets

python -m src.cli init-db      # create tables + seed the org/admin
uvicorn src.main:app --reload --port 8000
```

- API + interactive docs: **http://localhost:8000/api/docs**
- CLI (collection, pipeline, etc.): `python -m src.cli <command>`
- Tests: `pytest` (from `be/`)

> All responses use the envelope `{ "success": bool, "data": …, "error": … }`.
> `GET /api/health` is the liveness check. Log in via `POST /api/auth/login` to get a
> Bearer token. Run backend commands from `be/` (the SQLite path is relative to the CWD).

### Frontend (`fe/`)

```bash
cd fe
npm install
npm run dev                    # Vite on :5173, proxies /api and /run to the backend :8000
# or build for the backend to serve at /:
npm run build                  # -> fe/dist
```

Log in with the `ADMIN_EMAIL` / `ADMIN_PASSWORD` you set in `be/.env`.

### Docker (backend only)

```bash
docker compose up              # builds be/ and serves the API on :8000
```

The frontend isn't dockerized — run it with `npm run dev`, pointed at the container.

---

## Adding a channel

Owners add their own channel in **Settings → Channels** (`POST /api/channels`) by
`@username` or `t.me` link. Channels are scoped to your organization, and the whole
pipeline (collection, analytics, planning) reads them from the database — the `.env`
`OWNED_CHANNELS` list is now only a fallback for a fresh install with no channels yet.

A new channel starts as **pending**: Telegram's numeric id isn't known until an
authenticated client resolves it. Turning it **active** is the one manual step:

1. Use a Telegram account that **administers** the channel and put its
   `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_PHONE` in `be/.env`.
2. Sign in once to create the MTProto session (`python -m src.cli telegram-login`,
   enter the code) — this writes a `*.session` file.
3. Run a sync (`python -m src.cli collect-owned @YourChannel`, the agent, or the
   `telegram_sync` cron — the agent and cron pick up every channel in the DB
   automatically). The collector resolves the `@username`, **adopts the pending row**, records the
   real channel id, and flips it to **active**. Posts and view stats then start flowing.

> Full history and broadcast stats (reactions, reach, subscriber growth) require the
> signed-in account to be an **admin** of the channel; a plain member gets views only.
> Multi-org self-serve today shares one MTProto session — per-org Telegram auth
> (bot-based) is the next milestone.

---

## Deployment

Two independent deploys: the **backend on Railway or Render** (Docker) and the
**frontend on Vercel** (static Vite build). Deploy the backend first — you need its
public URL for the frontend and its CORS setting.

### Backend → Railway

1. **New Project → Deploy from GitHub repo** → pick this repo.
2. In the service **Settings → Root Directory**, set **`be`** (so the build context is
   the backend). Railway reads `be/railway.json` and builds `be/Dockerfile`.
3. Add a **Volume** mounted at **`/app/data`** so the SQLite DB + snapshots survive
   redeploys.
4. **Variables** — set: `ENVIRONMENT=production`, `SCHEDULERS_AUTOSTART=true`,
   `AUTH_SECRET` (long random string), `ADMIN_EMAIL`, `ADMIN_PASSWORD`,
   `CORS_ORIGIN` (your Vercel URL, e.g. `https://dealwing.vercel.app`),
   `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE`, `GROQ_API_KEY`,
   `API_SECRET_KEY`. `PORT` is injected by Railway automatically.
5. Deploy. The admin user is auto-seeded on first boot; check `GET /<url>/api/health`.

### Backend → Render (alternative)

The repo ships a `render.yaml` blueprint. **New → Blueprint → pick this repo**; Render
builds `be/Dockerfile`, attaches a 1 GB disk at `/app/data`, and prompts for the
`sync: false` secrets (`CORS_ORIGIN`, `ADMIN_*`, `TELEGRAM_*`, `GROQ_API_KEY`,
`API_SECRET_KEY`). `AUTH_SECRET` is generated for you. Health check: `/api/health`.

### Frontend → Vercel

1. **Add New Project** → import this repo.
2. Set **Root Directory** to **`fe`** (Vercel auto-detects Vite from `fe/vercel.json`).
3. Add an environment variable **`VITE_API_URL`** = your backend URL (no trailing
   slash), e.g. `https://dealwing-backend.up.railway.app`.
4. Deploy. `vercel.json` rewrites all routes to `index.html` for the SPA router.
5. Back on the backend, make sure `CORS_ORIGIN` equals the final Vercel URL
   (any `*.vercel.app` preview domain is already allowed).

### Deploy notes (honest caveats)

- **Run one backend instance.** The cron scheduler uses a single-leader lock; keep
  replicas at 1 (`numReplicas`/`--workers 1`) so jobs don't double-fire.
- **SQLite is ephemeral without the disk/volume** above — data resets on redeploy if
  you skip it. For heavier use, point `DB_URL` at managed Postgres.
- **Deal scraping (GrabCash) may 403 from cloud IPs.** The source's Cloudflare has
  been permissive from an India IP but can block US/EU datacenter ranges; if scraping
  degrades on the host, the rest of the app (analytics, planning, UI) still runs.
- **Telegram login** needs an interactive first sign-in (a code). Generate the
  `*.session` locally, or run the login flow once against the deployed instance.

---

## Tech stack

| Layer     | Stack                                                                 |
| --------- | --------------------------------------------------------------------- |
| Frontend  | Vite, React, TypeScript, TailwindCSS, shadcn/ui, TanStack Query, Axios, Recharts |
| Backend   | FastAPI, Uvicorn, SQLAlchemy, Typer, APScheduler, Groq (LLM)          |
| Auth      | PBKDF2 password hashing + HMAC‑signed tokens (stdlib)                 |
| Storage   | SQLite (default)                                                      |
| Infra     | Docker (backend)                                                      |

## Configuration

Backend settings are environment‑driven — see `be/.env.example`. Frontend settings
(the API base URL) are in `fe/.env.example`. Secrets are never committed.
