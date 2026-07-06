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
