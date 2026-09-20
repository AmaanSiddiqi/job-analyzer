# Landed

[![CI](https://github.com/AmaanSiddiqi/job-analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/AmaanSiddiqi/job-analyzer/actions/workflows/ci.yml)

Job-search intelligence for international students and new grads in Canada. Named for the two things its users are working toward — *landing* a job, and *landed* status.

Every posting is parsed by an LLM into structured components — skills, seniority, compensation, and the eligibility gates that actually decide who can apply (minimum years of experience, degree, French, citizenship/clearance), each backed by a verbatim quote from the posting. The goal is **explained, eligibility-aware matching**: "your Python/AWS matches; they want 5+ years and you have 2; posted 2 days ago."

**Live:** [jobs.amaansiddiqi.me](https://jobs.amaansiddiqi.me) · API on Railway · frontend on Vercel

> **Status (P1 complete, backfill running):** ~8,200 postings from 69 identity-verified Greenhouse/Lever/Ashby company boards plus the Adzuna and Jooble aggregators, polled every 6 hours. The LLM extraction pipeline beats the frozen spaCy baseline by **+0.370 F1** and runs as scheduled Message Batches at **$0.0067 per posting**. The dashboard serves those extracted skills, so "go to market" is no longer counted as the Go language. See [CHANGELOG.md](CHANGELOG.md) and [reports/p1_report.md](reports/p1_report.md).

## Stack

| Layer      | Tech                                                                    |
|------------|-------------------------------------------------------------------------|
| Backend    | Python 3.12, FastAPI, SQLAlchemy 2 (async), asyncpg, Alembic, APScheduler |
| Database   | PostgreSQL 18 (Railway), migration-managed schema                       |
| Extraction | Claude Sonnet 5 structured outputs via the Message Batches API; spaCy PhraseMatcher kept as the frozen eval baseline |
| Evaluation | Machine-assisted labeling (a different, stronger model as annotator) + P/R/F1 harness |
| Frontend   | React 18, TypeScript, Vite, Tailwind CSS, Recharts                      |
| Quality    | ruff, mypy, pytest (264 tests), ESLint — all enforced in GitHub Actions CI |
| Security   | Shared-secret admin gate + per-IP rate limits (slowapi) on every write  |
| Deploy     | Railway (API + Postgres, migrations auto-apply), Vercel (frontend)      |

## What's interesting here

- **Evaluated, not vibes.** A 150-listing gold set (a stronger annotator model drafts, a human reviews every disagreement, each label carries a `human_verified` flag) scores the extractors:

  | Extractor | Precision | Recall | F1 |
  |---|---|---|---|
  | spaCy baseline (frozen) | 0.874 | 0.312 | 0.460 |
  | **Claude Sonnet 5, thinking off** | **0.916** | **0.758** | **0.830** |
  | Claude Sonnet 5, thinking on | 0.913 | 0.757 | 0.828 |
  | Claude Haiku 4.5 | 0.864 | 0.654 | 0.744 |

  Recall more than doubles while precision *rises*. Haiku came out worse **and** 2x the cost: its cached prefix measures 3,337 tokens, under Haiku 4.5's 4,096-token caching minimum, so prompt caching never engages. Full write-up: [reports/extraction_eval_llm.md](reports/extraction_eval_llm.md).

- **Cost engineering from measurement, not assumption.** Batches are half price on paper, but a real batch cost the same as live calls — concurrent requests never find the prompt cache warm, so every one paid a 4,322-token cache write. One live warm-up request with a 1-hour TTL before each submission turned 0/6 cache reads into 5/5, and **$0.0149 → $0.0067 per posting**. A $15 per-run cap is checked *before* anything is sent, sized for the worst case so it holds even when caching doesn't.

- **The schema limit nobody documents.** Anthropic's structured-output compiler rejects schemas as "too complex" based on **field order**: the same 14 fields compile with nested models first and fail with them last, at a byte-identical size. Found by bisecting against the live API; recorded in [`schema.py`](backend/app/extraction/schema.py).

- **Evidence-gated claims.** A "5+ years required" that the model invented would wrongly exclude a user from a job they could get. Pydantic validators reject any experience requirement or visa flag without a verbatim quote, then retry once, then dead-letter.

- **Resumable, idempotent pipeline.** Batches are tracked in Postgres so a deploy can't orphan paid-for results; collection is idempotent; a circuit breaker stops a systematically failing batch from being retried live at double the price; one bad batch can't wedge the rest.

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

Ingestion and extraction are off by default; enable them with `ENABLE_BOARD_INGESTION`, `ENABLE_AGGREGATOR_INGESTION` and `ENABLE_LLM_EXTRACTION` (the last also needs `ANTHROPIC_API_KEY`).

## Tests & linting

```bash
make test    # backend: pytest — no live network; the Anthropic client is stubbed
make lint    # ruff + mypy + eslint
```

Or directly: `cd backend && uv sync --extra dev && uv run pytest tests/ -v`

## Evaluation harness

```bash
make eval-smoke       # CI-safe: score baseline vs 10 fixture listings (no DB/API key)
make eval-export      # sample real listings from the DB into a labeling pool
make eval-draft       # draft-label with the annotator model (needs ANTHROPIC_API_KEY)
make eval-review      # keyboard-driven human review (SAMPLE_SIZE=40 to cap)
make eval-extraction  # score baseline vs the reviewed gold set → reports/

# LLM extractor configs (cached predictions — scoring is free and re-runnable)
cd backend
uv run python -m eval.scripts.predict_llm --config sonnet-nothinking --limit 10
uv run python -m eval.scripts.score_llm --report ../reports/extraction_eval_llm.md
```

Full protocol in [backend/eval/README.md](backend/eval/README.md).

## API

| Method | Path                                   | Auth  | Description |
|--------|----------------------------------------|-------|-------------|
| GET    | `/jobs`                                | —     | List postings; filters AND together (`q`, `skill`, `company`, `location`, `source_type`, `since_days`) |
| GET    | `/jobs/count`                          | —     | Total for the same filters, for pagination |
| GET    | `/jobs/{id}`                           | —     | Single posting |
| GET    | `/trends/skills`                       | —     | Top skills by frequency (`top_n`) |
| GET    | `/trends/skills/history`               | —     | Weekly share of postings per skill, bucketed by date posted (`skills[]`, `weeks`) |
| GET    | `/trends/roles`, `/trends/companies`   | —     | Most common titles / most active companies (`top_n`) |
| GET    | `/trends/sources`                      | —     | Counts per ingestion source, all-time and last 7 days |
| GET    | `/trends/stats`                        | —     | Summary stats |
| POST   | `/ingest/boards`, `/ingest/aggregators`| admin | Run an ingestion pass (also scheduled every 6h) |
| GET    | `/ingest/suggestions`                  | admin | Verified company-board discoveries, as `companies.yaml` entries |
| POST   | `/extract/batch`                       | admin | Submit pending postings as a Message Batch (also scheduled every 45 min) |
| POST   | `/extract/collect`                     | admin | Collect finished batches now |
| POST   | `/extract`                             | admin | Live (non-batch) extraction run |
| GET    | `/admin/extraction-status`             | admin | Coverage over eligible postings, in-flight batches, spend |
| GET    | `/admin/deadletters`                   | admin | Failed extractions; `POST .../{id}/requeue` makes one eligible again |
| GET    | `/admin/unmapped-skills`               | admin | Skills outside the taxonomy, for weekly review |
| POST   | `/jobs`                                | admin | Insert a posting |
| POST   | `/scrape`, `/scrape/bulk`              | admin | Deprecated LinkedIn scraper (503 unless explicitly enabled) |
| GET    | `/health`                              | —     | Health check |

Admin routes take an `X-Admin-Key` header (`ADMIN_API_KEY` env var) and fail closed if it's unset.

## Project structure

```
backend/
  alembic/               # Migrations — source of truth for the DB schema
  app/
    extraction/          # LLM pipeline: schema, prompts, client, batch, cost caps
    ingestion/           # Greenhouse/Lever/Ashby boards, Adzuna/Jooble, company discovery
    routes/              # jobs, trends, ingest, extract, admin, scrape (deprecated)
    services/            # nlp.py (frozen spaCy baseline), skills normalization
    scheduler.py         # APScheduler: ingestion every 6h, extraction every 45 min
    models.py            # ORM: job_postings, raw_listings, listing_components, ...
  sources/companies.yaml # 69 identity-verified company boards (a growing seed)
  taxonomy/skills.yaml   # 201 canonical skills + 388 aliases
  eval/                  # Gold set, labeling tools, LLM predict/score scripts
  scraper/linkedin.py    # Deprecated — gated off, do not extend
  tests/

frontend/src/
  App.tsx                # Dashboard layout + data loading
  api/                   # Typed fetchers, admin-key session handling
  components/            # Filters, job table, trend charts

reports/                 # Eval reports + per-phase closeout reports
CLAUDE.md                # Product spec & phase plan
AWS.md                   # AWS migration plan (P1.4) — phases + cutover checklist
CHANGELOG.md             # Per-phase change log
V2.md                    # Parked ideas, with the reasoning
```

## Roadmap

The full phase plan lives in [CLAUDE.md](CLAUDE.md); the AWS migration plan is in [AWS.md](AWS.md). Next: switch the dashboard's skill data to the LLM extractor once the backfill completes, **Workday ingestion** (Canadian banks, telecoms and enterprises hire overwhelmingly on Workday — the coverage that replaces LinkedIn), then cross-board dedup (P2), user accounts with resume upload (P3), and per-user explained matching (P5).
