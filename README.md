# Landed

[![CI](https://github.com/AmaanSiddiqi/job-analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/AmaanSiddiqi/job-analyzer/actions/workflows/ci.yml)

Job-search intelligence for international students and new grads in Canada. Named for the two things its users are working toward — *landing* a job, and *landed* status.

Live app: ~7,200 indexed Canadian tech postings ingested from Greenhouse/Lever/Ashby company boards plus the Adzuna and Jooble aggregators, with spaCy skill extraction and a filterable dashboard of hiring trends. Visa/sponsorship signal extraction with verbatim evidence is the flagship feature in progress.

**Live:** [jobs.amaansiddiqi.me](https://jobs.amaansiddiqi.me) · API on Railway · frontend on Vercel

> **Status (P0 complete):** foundations are done — Alembic migrations, CI, an evaluation harness with a human-reviewed gold set, auth + rate limiting on mutating routes. The original LinkedIn scraper is deprecated and gated off (ToS risk; unsuitable for a multi-user product), so the corpus is frozen until P1 replaces it with official sources (Greenhouse/Lever/Ashby board APIs, Adzuna, Jooble). See [CHANGELOG.md](CHANGELOG.md) and [reports/p0_report.md](reports/p0_report.md).

## Stack

| Layer      | Tech                                                              |
|------------|-------------------------------------------------------------------|
| Backend    | Python 3.12, FastAPI, SQLAlchemy 2 (async), asyncpg, Alembic      |
| Database   | PostgreSQL 18 (Railway), migration-managed schema                 |
| NLP        | spaCy `en_core_web_sm` + PhraseMatcher (~200-term curated vocab)  |
| Evaluation | Machine-assisted labeling (Claude as annotator) + P/R/F1 harness  |
| Frontend   | React 18, TypeScript, Vite, Tailwind CSS, Recharts                |
| Quality    | ruff, mypy, pytest, ESLint — all enforced in GitHub Actions CI    |
| Security   | Shared-secret admin gate + per-IP rate limits (slowapi) on writes |
| Deploy     | Railway (API + Postgres, migrations auto-apply), Vercel (frontend)|

## Features

- **Skill extraction** — spaCy PhraseMatcher over a curated vocabulary; case-insensitive, multi-word aware ("machine learning", "spring boot"). Serves as the frozen eval baseline for the LLM extractor coming in P1.
- **Trends dashboard** — stats cards, skill-demand-over-time line chart, top skills / roles / companies bar charts, click-to-filter by company, searchable job table.
- **Evaluated, not vibes** — a 150-listing gold set (built with machine-assisted labeling: Claude drafts, human reviews disagreements, every label carries a `human_verified` flag) puts the baseline extractor at **precision 0.874 / recall 0.312 / F1 0.460**. That recall gap — modern AI/ML terms, niche tools, non-engineering domains — is the measured case for the LLM extraction pipeline, and the bar it has to beat. A 10-item smoke eval runs in CI on every push.
- **Migration-managed schema** — Alembic baseline rehearsed against a prod snapshot before cutover; deploys run `alembic upgrade head` automatically.
- **Gated writes** — `POST /scrape`, `POST /scrape/bulk`, and `POST /jobs` require an `X-Admin-Key` header and are rate-limited per IP; routes fail closed if the key is unconfigured.

## Local dev

### With Docker (recommended)

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

API docs → <http://localhost:8000/docs>

### Without Docker

```bash
# Backend
cd backend
uv sync
uv run python -m spacy download en_core_web_sm
cp .env.example .env
uv run alembic upgrade head            # schema is Alembic-managed, not auto-created
uv run uvicorn app.main:app --reload   # → :8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev   # → :5173
```

## Tests & linting

```bash
make test    # backend: pytest (26 tests — API, NLP, eval scoring)
make lint    # ruff + mypy + eslint
```

Or directly: `cd backend && uv sync --extra dev && uv run pytest tests/ -v`

## Evaluation harness

```bash
make eval-smoke       # CI-safe: score baseline vs 10 fixture listings (no DB/API key)
make eval-export      # sample real listings from the DB into a labeling pool
make eval-draft       # draft-label with Claude (needs ANTHROPIC_API_KEY)
make eval-review      # keyboard-driven human review (SAMPLE_SIZE=40 to cap)
make eval-extraction  # score baseline vs the reviewed gold set → reports/
```

Full protocol in [backend/eval/README.md](backend/eval/README.md); latest results in [reports/extraction_eval.md](reports/extraction_eval.md).

## API

| Method | Path                     | Auth        | Description                                          |
|--------|--------------------------|-------------|------------------------------------------------------|
| GET    | `/jobs`                  | —           | List postings (`skip`, `limit`, `location`, `company`) |
| GET    | `/jobs/{id}`             | —           | Single posting                                       |
| GET    | `/trends/skills`         | —           | Top skills by frequency (`top_n`)                    |
| GET    | `/trends/roles`          | —           | Most common job titles (`top_n`)                     |
| GET    | `/trends/companies`      | —           | Most active companies (`top_n`)                      |
| GET    | `/trends/skills/history` | —           | Weekly skill counts (`skills[]`, `weeks`)            |
| GET    | `/trends/stats`          | —           | Summary stats                                        |
| POST   | `/jobs`                  | admin key   | Insert a posting (10/min)                            |
| POST   | `/scrape`                | admin key   | Manual scrape (5/min; currently 503 — source deprecated) |
| POST   | `/scrape/bulk`           | admin key   | Background bulk scrape (2/min; currently 503)        |
| GET    | `/health`                | —           | Health check                                         |

Admin-gated routes take an `X-Admin-Key` header (`ADMIN_API_KEY` env var).

## Project structure

```
backend/
  alembic/               # Migrations — source of truth for the DB schema
  app/
    main.py              # FastAPI app, CORS, rate-limit wiring, lifespan
    auth.py              # X-Admin-Key gate (interim until Clerk in P3)
    rate_limit.py        # slowapi per-IP limiter
    database.py          # Async engine + session factory
    models.py            # JobPosting ORM (+ index declarations)
    schemas.py           # Pydantic v2 request/response models
    scheduler.py         # APScheduler — gated by ENABLE_LINKEDIN_SCRAPER
    routes/              # jobs, trends, scrape
    services/
      nlp.py             # spaCy skill extractor (frozen eval baseline)
      scraper.py         # Scrape pipeline: listings → descriptions → NLP → DB
  eval/
    schemas.py           # Label data model (human_verified per row)
    fixtures/            # 10 hand-authored smoke-eval listings
    gold/                # 150-listing gold set (intermediates gitignored)
    scripts/             # export → draft_label → review_cli → score_extraction
  scraper/
    linkedin.py          # Deprecated — gated off, do not extend
  tests/                 # API, NLP, and eval-scoring tests

frontend/
  src/
    App.tsx              # Dashboard layout + data loading
    api/                 # Typed fetchers, admin-key session handling
    components/          # SkillHistory/Skills/Roles/Companies charts, JobTable

reports/                 # Eval reports + per-phase closeout reports
CLAUDE.md                # Product spec & phase plan (P0 ✅ → P1 next)
CHANGELOG.md             # Per-phase change log
AUDIT.md                 # P0 codebase audit (closed — historical record)
```

## Roadmap

The full phase plan lives in [CLAUDE.md](CLAUDE.md). Next up — **P1: Sources & extraction**: replace the deprecated scraper with official board APIs (~100 Canadian companies) + Adzuna/Jooble, and add an LLM extraction pipeline producing structured job components — including **visa/sponsorship signals with verbatim evidence**, the product's core feature.
