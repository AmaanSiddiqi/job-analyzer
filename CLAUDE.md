# CLAUDE.md — Job Analyzer → Product

This file guides Claude Code working in this repository. It merges the repo's existing setup docs with the product upgrade spec. Where they conflict, this file wins.

You are working on jobs.amaansiddiqi.me — a **live** app (FastAPI backend on Railway, React frontend on Vercel). The owner is Amaan. The goal: evolve this from a single-user analyzer into a **shipped product with real users** — job-search intelligence for international students and new grads in Canada, with **visa/sponsorship intelligence** as the flagship feature. Treat it as production at all times.

## Current state of the repo (as-is, before upgrade)

**Backend** (`backend/app/`, Python managed with **uv** — never add a requirements.txt):
- `main.py` FastAPI app; **tables currently created on startup via lifespan — this is replaced by Alembic in P0**.
- `database.py` async SQLAlchemy (asyncpg); all DB access is async — never use sync calls.
- `models.py` `JobPosting` ORM; `skills` is Postgres `ARRAY(String)`, lowercase-normalized; `source_url` UNIQUE is the current (URL-level) dedup.
- `routes/`: `jobs.py` (CRUD + `?location=`), `trends.py` (`/trends/skills` via `unnest`+GROUP BY, `/trends/roles`), `scrape.py` (`POST /scrape`: fetch cards → concurrent description fetch, semaphore=3 → NLP → bulk upsert `on_conflict_do_nothing`).
- `services/nlp.py`: spaCy PhraseMatcher over curated `_SKILLS_VOCAB`; `extract_skills(text)`; 50k-char truncate. **This becomes `baseline_extractor` — the frozen eval baseline. Never delete it.**
- `scraper/linkedin.py`: LinkedIn guest-endpoint scraper (BeautifulSoup/lxml, 429 backoff). **See "Data source transition" — being deprecated.**

**Frontend** (`frontend/src/`, Vite + React + TS): Axios client (`baseURL:/api`, Vite proxy in dev), typed fetchers in `api/jobs.ts`, Recharts dashboards (`SkillsChart`, `RolesChart`), `JobTable`, single-page `App.tsx`.

**Commands:**
```bash
# backend
cd backend && uv sync && uv run python -m spacy download en_core_web_sm
cp .env.example .env   # DATABASE_URL + CORS_ORIGIN
uv run uvicorn app.main:app --reload        # :8000
# frontend
cd frontend && npm install && npm run dev   # :5173 ; npm run build ; npm run lint
# full stack
docker compose up --build
```

## Product thesis

**Wedge:** every listing parsed for sponsorship availability, work-authorization requirements, and PR-track signals, with verbatim evidence — plus cross-board dedup ("one card per real job, seen on N boards") and explained match scores against the user's uploaded resume. Amaan (PGWP holder) is user #1; his UBC network is initial distribution. v1 is free; design the data model so a paid tier can be added later, but build no billing.

## Data source transition (important — read first)

The current sole source is LinkedIn guest-endpoint scraping. That was acceptable for a personal tool; **it is not acceptable for a multi-user product** (ToS risk, brittleness). The upgrade replaces it:

1. **Primary:** Greenhouse / Lever / Ashby public board JSON endpoints, driven by `sources/companies.yaml` (~100 Canadian tech companies to start; curated in P1, Amaan reviews).
2. **Breadth:** Adzuna and Jooble free APIs.
3. **Fallback only:** Firecrawl-backed scraping of individual company career pages — robots.txt respected, honest user-agent, per-source rate limits.

`scraper/linkedin.py` is **deprecated**: gate it behind an env flag defaulting to off, stop scheduling it, do not extend it. Existing LinkedIn-sourced rows stay in the DB for continuity but get `source_type` labels; they will age out via staleness. Do not delete without asking.

## Target architecture

```
Sources (board JSONs, Adzuna/Jooble, Firecrawl fallback)
   ↓  Arq workers on Redis (Railway add-on) — idempotent, content-hash keyed, cost-capped
raw_listings (append-only) → LLM extraction → listing_components
   → entity resolution → canonical_listings ←→ listing_sources (N:1)
   → indexing: pgvector embeddings + Postgres FTS + entity tables
API: FastAPI (JSON, auth-protected) ←→ Clerk
Frontend: existing Vite+React app, upgraded in place (Tailwind + shadcn/ui) on Vercel
Users: resume upload (native PDF to LLM) → profile extraction → review → per-user feed
Feed: materialized user_feed table, refreshed nightly + on signup/profile change,
      Redis-cached responses — never full-corpus scoring per request
Retention: Resend + React Email digests
Analytics: PostHog (events + replay) · Sentry (errors) · Logfire (traces/metrics;
           keep /metrics endpoint so Prometheus/Grafana can bolt on later)
```

**Stack decisions (made — don't relitigate):** Railway keeps API + workers + Postgres(+pgvector) + Redis. **Frontend stays Vite + React** — upgrade in place with Tailwind + shadcn/ui; no Next.js rewrite (the app is auth-gated, SEO doesn't apply; landing page is a static route). Clerk free tier for auth (React SDK on frontend, JWKS verification middleware on FastAPI). Local sentence-transformers embeddings (bge-small-en-v1.5) on CPU. uv for Python deps. Ask before adding any other paid service.

## Core pipeline

1. **Structured extraction** — schema-constrained LLM parsing (below). Eval baseline: the existing spaCy `baseline_extractor`.
2. **Entity resolution / dedup** — canonical listings across boards (decoupling + hierarchical aggregation per arXiv:2602.02007). Current URL-level dedup remains at ingest; canonical dedup layers above it.
3. **Multi-signal matching** — per-user: embeddings + FTS + skill/seniority overlap; fusion baseline **RRF** (hand-tuned weights only if they beat RRF on eval); visa compatibility as default-on hard filter with a user toggle to soft-rank; per-signal contributions stored and shown.
4. **Feedback loop** — per-user application outcomes adjust ranking weights (simple boosts, no trained model in v1).

## Extraction schema (Pydantic v2, v1 — extend only with reason)

`JobComponents`: title_raw, title_normalized, seniority enum (intern/junior/mid/senior/staff/lead/unknown), company_raw, company_canonical, skills (canonical taxonomy IDs), skills_unmapped (review queue), required_quals, preferred_quals, `Compensation` (min/max/currency ISO-4217/period year|month|hour/is_estimated), location_raw + city/region/country (ISO-3166), remote_policy enum, `VisaSignals` (sponsorship_available, requires_existing_authorization, citizenship_or_pr_required — all `bool | None` where None = not stated — plus `evidence: list[str]` of verbatim phrases), posted_at, language, extraction_confidence.

Rules: structured-output mode; validation failure → one retry with the error appended → dead-letter with raw response stored. Never guess comp or visa values; every visa flag requires evidence. Skill taxonomy in `taxonomy/skills.yaml` — seed it FROM the existing `_SKILLS_VOCAB`, cap ~200, alias map, no auto-expansion; unmapped skills accumulate for weekly review. Extraction prompt versioned (`prompt_version` on every row); prompt changes require re-running the eval set and reporting the F1 delta before any backfill.

## Multi-user model

- Tables: `users` (Clerk ID external key), `user_profiles` (resume-extracted: taxonomy skills, seniority, target roles, locations, user-declared work-authorization status e.g. "PGWP until 2029" / "needs sponsorship"), `user_applications`, `user_saved_listings`, `user_feed_events`.
- Resume upload: **PDF sent natively to the LLM** (no pdfplumber/pypdf pre-extraction — multi-column resumes mangle text extraction); text fallback only past model limits; user reviews/edits the extracted profile before save.
- Privacy: per-user only, never shared, never used for training; `DELETE /me` removes everything including embeddings and feed rows, from day one; no personal data in logs; authorization status is sensitive — used only for the user's own filtering. Resume re-upload → profile versioning, latest wins.
- Amaan's current setup migrates to user #1.

## Frontend upgrade (in place)

Add Tailwind + shadcn/ui to the Vite app; consistent spacing/type scale, dark mode, skeleton loaders, mobile-first. Views: **Landing** (value prop for international candidates, sign-up) · **Feed** (canonical cards: title, company, comp, "seen on N boards", **visa badge** — Sponsors ✓ / No sponsorship ✗ / Not stated, evidence phrases on hover; match score with per-signal breakdown on expand) · **Listing detail** (structured fields + snippet + prominent link to original — never the full description) · **Profile editor** · **Application tracker** (kanban: saved → applied → response → interview). Existing Recharts trend components stay as a "market trends" page. The visa badge with evidence popover is the screenshot that sells the product — make it excellent. Admin (dead-letters, merge audit) stays plain HTML.

## Non-negotiables

- **Never break the live site.** New pipeline runs behind feature flags; spaCy baseline and current feed keep working until cutover is approved by Amaan.
- **Alembic introduced in P0**: baseline the current schema, remove lifespan table-creation, every change a reversible migration rehearsed on a prod copy, snapshot before applying. The multi-user migration is the riskiest step — its own reviewed PR.
- **Cost caps:** `llm_usage` spend counter, hard abort past cap (default $15/run); batch API for backfills.
- **Idempotent, resumable jobs**; 3 attempts → dead-letter table; `/admin/deadletters` to inspect/requeue.
- **Secrets** env-only via Railway/Vercel. **Ask before:** paid services, public API contract changes, data deletion, any ToS-grey scraping, scope beyond this file.
- No Kubernetes, no Kafka, no microservices split. One API, one worker service, one frontend.

## Scenario handling (implement, don't improvise)

Malformed/truncated listings → partial extract, low confidence, never fabricate. Non-English → detect, store language, dead-letter if unparseable. Comp → original currency preserved + `comp_cad_annual_est` from hardcoded rates table. Dedup ambiguity → blocking on (company_canonical × title trigram sim > .6 × country), merge only above component-agreement threshold — false merges worse than duplicates; audit log + manual split/merge endpoints. Repost 30+ days → new canonical with `repost_of`. Stale (unseen 14 days) → excluded from feeds, kept for history; notify users who saved/applied. LLM rate limits → backoff, circuit breaker, DB-tracked resumable batches. Per-source health metric vs trailing average → alert, never crash. `embedding_model` stored per row; model change = full re-embed, never mixed similarity. New-user cold start → profile-only matching works with zero feedback. 429s from board APIs → per-source rate budget.

## Data & legal guardrails

- **Never republish full listing descriptions.** Full text internal only; all views show structured fields + short snippet + link to the original. The extracted structure IS the product.
- Scrapers: robots.txt, honest user-agent, per-source rate limits.
- Resumes and authorization status are personal information (PIPEDA): minimum collection, matching-only use, zero retention after `DELETE /me`.
- Privacy policy + ToS pages in P6 launch checklist.

## Evaluation & product metrics

- `eval/`: 150-listing gold set built with **machine-assisted labeling** — human time target under 2 hours total, not evenings of manual work. Protocol: (1) a draft-label script using a **stronger annotator model that is different from the production extraction model** (same-model labeling makes the eval circular and worthless); (2) a keyboard-driven review flow (minimal web page or CLI) showing each listing beside its draft labels for accept/one-key-fix; (3) automatic disagreement flags wherever the annotator and the production extractor differ — mandatory human review there, 25% random audit everywhere else. Dedup labels: blocking proposes candidate pairs, annotator model judges same/different, human reviews disagreements only. Relevance labels for the matching eval: seed implicit positives from Amaan's existing saves/applications, then a quick yes/maybe/no pass (~30 min). Store a `human_verified` flag per label so published eval claims stay honest.
- Extraction: per-field P/R/F1, LLM vs `baseline_extractor` (spaCy). Dedup: pairwise P/R + dedup ratio. Matching: precision@10, NDCG@10 vs keyword baseline. `make eval-*` targets; 10-item smoke eval in CI; reports rendered to `reports/` markdown.
- PostHog from day one: signups, resumes uploaded, feed sessions, saves, applications tracked, digest open→click.

## Phases & definition of done

1. **P0 Audit & foundations:** FIRST, before writing any feature code, read the entire codebase and produce `AUDIT.md`: every place the code diverges from this file or the old docs, bugs, dead code, missing error handling, missing DB indexes, dependency problems, and security gaps — in particular, `POST /scrape` and any other mutating endpoint currently has no auth or rate limiting; flag every unprotected mutating route, and check CORS config against the deployed origins. Fix small, safe issues in dedicated PRs immediately; assign bigger findings to their relevant phase as tracked items. THEN: git tag + DB snapshot; introduce Alembic and baseline the schema (drop lifespan table-creation); isolate `baseline_extractor`; eval scaffolding + machine-assisted labeling tooling; CI (ruff, mypy, pytest, smoke eval). DoD: `AUDIT.md` reviewed by Amaan; `make eval-*` runs end-to-end on draft labels; migrations rehearsed on a prod copy.
2. **P1 Sources & extraction:** `sources/companies.yaml` (~100 Canadian boards, Amaan reviews) + Adzuna/Jooble ingestion + deprecation flag on LinkedIn scraper; extraction pipeline + cost caps + dead-letters + visa signals; extraction eval. DoD: ≥90% of ingested listings extracted; F1 report published; per-source counts visible.
3. **P2 Dedup:** canonical listings + audit endpoints. DoD: dedup eval report; "seen on N boards" data live.
4. **P3 Multi-user foundation:** Clerk (frontend SDK + FastAPI JWKS middleware), user/profile schema, resume upload → native-PDF extraction → review flow, Amaan as user #1, `DELETE /me`. DoD: a second test account works end-to-end. Riskiest phase — small PRs.
5. **P4 Frontend upgrade:** Tailwind + shadcn in place; landing, feed with visa badges, detail, profile editor, tracker. DoD: Amaan uses the new UI daily; old dashboard still reachable.
6. **P5 Per-user matching:** RRF fusion, visa filter+toggle, explanations, materialized `user_feed`, feature flag. DoD: matching eval beats baseline; Amaan approves cutover.
7. **P6 Retention & launch:** Resend digests, PostHog, Sentry, Logfire, per-source health dashboard; privacy/ToS pages, API rate limiting; launch checklist. DoD: digest ships daily to Amaan for a week clean.
8. **P7 Feedback loop:** outcome-based weight adjustments per user.

## Working conventions

uv for Python (no requirements.txt); all DB access async; skills lowercase before storing; small conventional-commit PRs; pytest with recorded LLM fixtures — no live network in unit tests; typed everywhere, ruff + mypy clean; CHANGELOG + `reports/` updated per phase; stop and ask at product decisions instead of choosing silently.

## Out of scope v1

Billing/Stripe, trained rerankers, auto-apply, resume generation, extending the LinkedIn scraper, mobile app, Kubernetes. Capture future ideas in `V2.md`.
