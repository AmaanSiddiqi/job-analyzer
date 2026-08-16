# Changelog

All notable changes to this project, organized by phase (see CLAUDE.md for the
phase plan). Dates are when the phase closed, not when it started.

## P0 — Audit & foundations (closed 2026-08-16)

The groundwork phase: no product features, but everything needed to build them
safely on a live app. PRs [#1](https://github.com/AmaanSiddiqi/job-analyzer/pull/1),
[#2](https://github.com/AmaanSiddiqi/job-analyzer/pull/2),
[#3](https://github.com/AmaanSiddiqi/job-analyzer/pull/3),
[#4](https://github.com/AmaanSiddiqi/job-analyzer/pull/4).
Full phase report: [reports/p0_report.md](reports/p0_report.md).

### Added
- **`AUDIT.md`** — full codebase audit against the CLAUDE.md product spec:
  security gaps, spec divergences, bugs, missing indexes, tooling problems.
  Every finding is now closed or explicitly assigned to a later phase.
- **Alembic migrations** (`backend/alembic/`) — schema is now migration-managed.
  Baseline `0001` was rehearsed against a restored production snapshot before a
  one-time `stamp head` on prod; `railway.toml`/`docker-compose.yml` run
  `alembic upgrade head` as a deploy step, so later migrations (like `0002`)
  apply themselves on deploy.
- **CI** (`.github/workflows/ci.yml`) — backend job (ruff, mypy, pytest, 10-item
  smoke eval) + frontend job (ESLint, Vite build) on every push/PR to `main`.
- **Eval harness** (`backend/eval/`) — machine-assisted labeling per CLAUDE.md's
  protocol: DB export → draft-labeling with Claude as annotator → keyboard-driven
  human review (`--sample-size` capped) → per-listing P/R/F1 scoring rendered to
  `reports/`. `make eval-*` targets; smoke eval runs in CI with zero external deps.
- **First extraction gold set** (150 real listings, 40 human-verified) and
  baseline numbers: `baseline_extractor` (spaCy) scores **precision 0.874 /
  recall 0.312 / F1 0.460**. Recall is the story — the fixed ~200-term vocab
  misses modern AI/ML terminology, specific tools, and all non-engineering skill
  domains. This is the bar P1's LLM extractor must clear.
- **Auth gate** (`app/auth.py`) — `POST /jobs`, `POST /scrape`, `POST /scrape/bulk`
  require an `X-Admin-Key` header checked against `ADMIN_API_KEY` (fails closed:
  unset → 503, not open). Stopgap until Clerk in P3. Frontend prompts for the key
  once per browser session instead of embedding a secret in the bundle.
- **Rate limiting** (`app/rate_limit.py`, slowapi) — per-IP: 5/min scrape,
  2/min bulk scrape, 10/min job create.
- **DB indexes** (migration `0002`) — `date_scraped DESC`, `company`,
  `lower(company)` expression index, `title`, GIN on `skills`. Applied to prod
  automatically by the deploy pipeline.
- `Makefile` with `eval-*`, `test`, `lint` targets; ruff + mypy configuration;
  ESLint 9 flat config (lint had been silently broken — no config existed).

### Changed
- **`scraper/linkedin.py` deprecated in practice, not just on paper** — gated
  behind `ENABLE_LINKEDIN_SCRAPER` (default **off**), scheduler no longer starts
  when the flag is unset, both scrape endpoints 503 with a clear message.
  Live auto-scraping is intentionally stopped until P1's board-JSON/Adzuna/Jooble
  sources replace it (data is frozen at 5,862 rows, last scraped 2026-08-11).
- `main.py` no longer creates tables via lifespan `create_all` — Alembic owns the
  schema.
- SQL `count` labels renamed to `n` in `trends.py` (SQLAlchemy `Row` is
  tuple-like; a column named `count` shadows `tuple.count()`).
- `zip()` in the scrape pipeline is now `strict=True` (silently misaligned
  listings/descriptions would have been a real bug).
- `database.py` uses `async_sessionmaker` (typed SQLAlchemy 2.0 API).
- Docs corrected: prod Postgres is 18, not 16; docker-compose bumped to match.
- `CLAUDE.md` un-gitignored and tracked (its header claimed it was checked in).

### Removed
- `backend/requirements.txt` — dead (nothing installed from it), drifted from
  `pyproject.toml`, and contradicted the uv-only rule.

### Security
- All three mutating routes were previously reachable by anyone with no auth and
  no rate limit (AUDIT.md §1) — now gated, rate-limited, and verified live in prod.
