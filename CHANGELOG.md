# Changelog

All notable changes to this project, organized by phase (see CLAUDE.md for the
phase plan). Dates are when the phase closed, not when it started.

## P1.4 phase 1 — Terraform skeleton + OIDC deploy (2026-09-20)

The first of the five AWS phases in [`AWS.md`](AWS.md). Infrastructure code
only: nothing in this change serves traffic, stores data or runs a job, and the
live site is still on Railway.

### Added
- **`infra/`** — Terraform for remote state (`bootstrap/`), a public-subnets
  VPC with a free S3 gateway endpoint and no NAT gateway, the `landed-backend`
  ECR repository with a lifecycle policy, and the GitHub Actions OIDC role.
  `infra/README.md` is the operator's manual.
- **`.github/workflows/deploy.yml`** builds and pushes the backend image to ECR
  on merge to `main`, authenticating by exchanging GitHub's OIDC token for a
  short-lived AWS session. **No AWS access keys exist in repository secrets.**
  The job skips itself while the `AWS_DEPLOY_ROLE_ARN` repository variable is
  unset, so main stays green until the stack is applied.
- **`terraform` job in CI** — `fmt -check` and `validate -backend=false`, which
  need no credentials and so run on pull requests from forks too.
- `make tf-bootstrap / tf-init / tf-plan / tf-apply / tf-fmt / tf-validate`.
  `tf-init` regenerates the gitignored backend config from the caller's own
  account id, because the state bucket name embeds it and this repo is public.

### Changed
- **`AWS.md`: no DynamoDB lock table.** The S3 backend's `dynamodb_table`
  argument was deprecated in Terraform 1.11 and removed in 1.14; S3 locking is
  native now (`use_lockfile = true`).
- **`AWS.md`: the signup-credits plan was written for a new account, and this
  is not one.** `905418381243` dates to October 2024 and already bills
  ~$1.26/mo from idle SageMaker Studio domains, so "year one is effectively
  free" cannot be assumed — the phase 5 budget alarm inherits that baseline.

## P1 follow-ups — dashboard reads extracted skills (2026-09-20)

PR [#18](https://github.com/AmaanSiddiqi/job-analyzer/pull/18). Live in
production the same day.

### Added
- **`TRENDS_USE_EXTRACTED_SKILLS`** switches the skills chart, the skill-history
  chart, the `?skill=` filter and job-card chips to LLM-extracted canonical
  taxonomy ids — all four together, because in the UI they are one loop: the
  chart fills the dropdown, the dropdown drives the filter, and every chip is a
  filter link. The API reports which source answered and the chart subtitle says
  so, because the two count different populations (~8,200 indexed postings vs
  the ~1,800 eligible board postings a user can still apply to).
- Migration `0008`: index on `raw_listings.source_url`, which joins postings to
  their extracted components.

### Fixed
- **The frozen baseline counted "go" as the Go language** in "go to market",
  "on-the-go" and "go-getter", inflating the chart and making the Go filter
  return marketing roles. Fixed by the cutover, not by patching the baseline —
  it is the frozen eval comparison and moving it would invalidate the published
  F1 numbers.
- **`npm run build` never typechecked** (no `tsc` in the script) and CI runs only
  lint + build, so a genuine type error passed both. `build` now runs
  `tsc --noEmit` first.

## P1 follow-ups — extraction goes live (2026-09-19)

The pipeline P1 built could not yet run in production: extraction was live-only
through an admin endpoint, nothing scheduled it, and the batch path the spec
requires for backfills didn't exist. PRs
[#15](https://github.com/AmaanSiddiqi/job-analyzer/pull/15) and
[#16](https://github.com/AmaanSiddiqi/job-analyzer/pull/16).

### Added
- **Batch extraction** (`app/extraction/batch.py`, migration `0007`) at
  **$0.0067/posting** — half the live price — scheduled every 45 minutes behind
  `ENABLE_LLM_EXTRACTION`. Submissions are tracked in `extraction_batches` so a
  deploy can't orphan paid-for results; failed results get one live retry then
  dead-letter; a circuit breaker stops a systematically failing batch from being
  retried live at double the price. Admin `POST /extract/batch` and
  `/extract/collect` for supervised runs.
- **Prompt-cache warm-up before every batch.** Measured: concurrent batch
  requests never find the cache warm (0/6 reads), which made batch no cheaper
  than live. One live request with the identical prefix and a 1-hour TTL turned
  that into 5/5 reads.

### Fixed
- **Duplicate extraction of edited postings** — `raw_listings` is append-only,
  and every version was selected: 2,521 rows for 1,782 postings, 29% waste.
- **Endless paid retries** — a posting that always failed was retried and billed
  every run, because dead letters were ignored; the requeue endpoint was a no-op.
- **A cost cap that only held when caching worked** — batches are now sized
  against the measured no-cache cost before submission.
- **The coverage metric could never pass the DoD** — it divided by every raw
  row, including 26k aggregator rows the pipeline never extracts; a finished
  backfill would have read ~6% against ≥90%. It now measures eligible postings.
- **One bad batch id would wedge extraction permanently**, retried every cycle.
- **1-hour cache writes** were priced at 1.25x instead of 2x.
- **Skill trend chart** plotted our ingestion history, not the market: it
  bucketed by scrape date, so the LinkedIn shutdown read as an outage and the
  board backfill as a spike. It now buckets by date posted and plots each
  skill's *share* of that week's postings, which survives the source change.
- **Top skills chart** labelled only every other bar.
- **Corrected published eval figures:** Haiku 4.5 is **2x** Sonnet's per-listing
  cost, not 3x (the 3x was its per-token discount), and the reason it never
  caches is a 3,337-token prefix under its **4,096**-token minimum — not the
  2,048 first cited. The eval report now computes the ratio instead of stating it.
- Tests that grepped function source text replaced with assertions on the
  compiled SQL.

## P1 — Sources & extraction (closed 2026-09-17)

Data flowing again and a structured-extraction pipeline that beats the frozen
spaCy baseline. PRs [#5](https://github.com/AmaanSiddiqi/job-analyzer/pull/5)–[#13](https://github.com/AmaanSiddiqi/job-analyzer/pull/13),
plus the schema fix on `p1/fix-structured-output-grammar`.
Full phase report: [reports/p1_report.md](reports/p1_report.md).
Eval: [reports/extraction_eval_llm.md](reports/extraction_eval_llm.md).

### Added
- **Board-JSON ingestion** for Greenhouse/Lever/Ashby driven by
  `backend/sources/companies.yaml` (69 identity-verified boards), behind
  `ENABLE_BOARD_INGESTION`. Ended the data freeze: corpus 5,862 → 7,193.
- **Adzuna/Jooble ingestion + aggregator-driven company discovery** — new boards
  are proposed into a review queue, never auto-added.
- **`taxonomy/skills.yaml`** — 201 canonical ids, 388 aliases, seeded from
  `_SKILLS_VOCAB`. Raised gold-set coverage 33% → 70.9%, which reframed the
  baseline's 0.312 recall as largely a vocabulary gap rather than a model one.
- **LLM extraction pipeline** (`app/extraction/`) — schema-constrained parsing
  into `listing_components`, eligibility and visa signals with verbatim
  evidence enforced by validators, per-run cost cap checked *before* each call,
  dead-letters, prompt versioning, resumable per-listing commits.
- **Extraction eval** — three configs × 150 listings, cached predictions so the
  report regenerates for free and CI can score without an API key.

### Changed
- **The product wedge moved from visa signals to eligibility-aware matching**,
  on measured evidence: sponsorship appears in 0.2% of 1,400 real Canadian
  descriptions, while experience requirements gate 27.9%. Visa signals stay as
  three cheap columns. See CLAUDE.md and `V2.md`.
- **`EXTRACTION_THINKING` defaults false on evidence, not assumption** — thinking
  on vs off measured identical in cost and within 0.002 F1.
- Extraction prompt at **v3**: teaches the sentinel conventions the schema
  requires and carries the ISO-4217/3166/639-1 semantics that used to live in
  `description=` strings.

### Fixed
- **The extraction pipeline could not make a single successful call** — the API
  rejected `JobComponents` with `400 "Schema is too complex."` Root cause was
  **field order**: the same fields compile when nested models are declared first
  and fail when they trail or interleave, at a byte-identical schema size.
- **Haiku rejected every request** (`does not support the effort parameter`),
  which would have reported the cheaper model at F1 0.000 rather than as
  untested.
- **One bad row aborted an entire paid eval run** via `asyncio.gather`, twice,
  while still exiting 0.
- **Thinking was never actually enabled** in the "thinking on" config; a test
  asserted the broken behaviour and so preserved it.
- **Cached prompt tokens were billed at zero** by `price_call`, understating
  spend in the module that enforces the cost cap.
- **Visa-signal yield reported 99%** against a corpus rate under 1% — the scorer
  tested `is not None` against a schema that now returns `"not_stated"`.
- **The prediction cache ignored `prompt_version`**, which would have mixed two
  prompts into one eval report.
- Per-segment Canada filter — "Amsterdam | Remote" and "Remote, KSA" were being
  kept; validated against 1,400 live production listings.
- Discovery ranking now sorts by Canadian-role count, not raw occurrences, which
  had sorted toward large US job-spammers.

### Security
- Tests were loading the developer's real `.env`, putting a live API key into
  mocked request URLs and making real network calls. An autouse fixture now
  nulls `Settings.model_config["env_file"]` (suite 22.6s → 0.9s).

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
