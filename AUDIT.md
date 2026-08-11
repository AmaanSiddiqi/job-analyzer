# AUDIT.md — P0 Codebase Audit

**Date:** 2026-08-11
**Scope:** Full read of `backend/` and `frontend/` as they exist today, checked against `CLAUDE.md`'s product spec and the old README. Nothing in this document has been fixed yet except where explicitly marked — this is the audit artifact CLAUDE.md's P0 requires be reviewed by Amaan before any feature code lands.

Legend: 🔴 security/data-risk · 🟠 correctness/reliability bug · 🟡 divergence from CLAUDE.md spec · ⚪ cleanup/dead code

---

## 1. Security gaps — unprotected mutating endpoints (P0 explicitly calls this out)

None of the three mutating routes have auth or rate limiting. All are reachable by anyone who finds the API.

| Route | File | Risk |
|---|---|---|
| 🔴 `POST /scrape` | [scrape.py:41](backend/app/routes/scrape.py:41) | Anyone can trigger outbound LinkedIn scraping on demand, `max_pages` up to 40. No auth, no rate limit, no per-caller cap. |
| 🔴 `POST /scrape/bulk` | [scrape.py:60](backend/app/routes/scrape.py:60) | Same, but fires a background task looping all 8 preset keywords × up to 40 pages. Nothing stops concurrent calls from stacking — two people (or one person double-clicking) hitting this back-to-back runs two full bulk scrapes in parallel against LinkedIn, worsening 429/ban risk. No lock/dedupe. |
| 🔴 `POST /jobs` | [jobs.py:38](backend/app/routes/jobs.py:38) | Raw insert endpoint — no auth. Anyone can write arbitrary `title`/`company`/`location`/`skills`/`raw_description`/`source_url` rows directly into the table shown on the public dashboard. `skills` here bypasses the NLP pipeline entirely, so lowercase-normalization (a stated working convention) isn't enforced on this path. No length cap on `raw_description`, so it's also an unbounded storage-abuse vector. |

**Recommendation for P0/P1:** gate these three behind a minimal shared-secret or admin-only check until Clerk lands in P3 (a full auth system is out of scope for P0, but *some* gate is not — CLAUDE.md's own P0 instructions call this the flagship P0 finding). Add per-IP rate limiting (`slowapi` is a lightweight fit for FastAPI). This is a "bigger finding," tracked for P0/P1, not a same-session fix.

## 2. CORS

[main.py:37-42](backend/app/main.py:37) — `allow_origins=[os.getenv("CORS_ORIGIN", "http://localhost:5173")]`. Single origin, sourced from one env var.

- 🟠 If `CORS_ORIGIN` is ever unset in the Railway prod environment, CORS silently falls back to `localhost:5173` and the live frontend breaks with opaque browser CORS errors — no startup-time validation that the env var is actually set in prod.
- 🟡 Only one exact origin can ever be allowed. Vercel preview deployments (every branch/PR gets a unique `*.vercel.app` URL) can't call the API. Not urgent for a single-maintainer app today, but will matter once collaborators/PRs show up.

## 3. `scraper/linkedin.py` is not deprecated in practice — this is the largest spec divergence

CLAUDE.md is explicit: *"`scraper/linkedin.py` is deprecated: gate it behind an env flag defaulting to off, stop scheduling it, do not extend it."*

What's actually in the repo:
- 🟡 [scheduler.py:43-52](backend/app/scheduler.py:43) schedules it unconditionally every `SCRAPE_INTERVAL_HOURS` (default 6h), started unconditionally from [main.py:23-24](backend/app/main.py:23) — no env flag gates it at all.
- 🟡 [services/scraper.py:79](backend/app/services/scraper.py:79) calls `linkedin.scrape()` directly and unconditionally — the only data source in the app today.
- 🟡 Per git log, it was *extended* after the CLAUDE.md spec was presumably in place ("expand scraping to Canada, add bulk historical load endpoint," "company-targeted scraping") — directly against "do not extend it."
- 🔴 Ties back to §1: this scraper is reachable by unauthenticated `POST /scrape*`, so an anonymous caller can drive LinkedIn traffic from the production server at will — the exact ToS/ban risk CLAUDE.md cites as the reason to deprecate it in the first place.
- 🟠 No robots.txt check, and `_HEADERS` in [linkedin.py:23-29](backend/scraper/linkedin.py:23) spoofs a Chrome desktop User-Agent rather than an honest one — the opposite of the "honest user-agent" rule CLAUDE.md sets for the Firecrawl fallback that's meant to replace this.
- 🟠 APScheduler runs in-process ([scheduler.py:24](backend/app/scheduler.py:24)). If Railway ever runs >1 instance of the API, every instance runs its own scheduler with no distributed lock — duplicate concurrent scrapes, compounding the ban risk above.

**Assignment:** P1 (source transition). Immediate P0-safe mitigation: add the env flag now (default off) so the behavior matches the CLAUDE.md contract even before Greenhouse/Lever/Adzuna sources exist — see §7 below for what I'd do this session with sign-off.

## 4. Missing DB indexes

[models.py](backend/app/models.py) has no explicit index besides the implicit one from `source_url UNIQUE`. Every other query pattern in the app does a full table/array scan:

- 🟠 `jobs.py` filters on `lower(location) LIKE %...%` and `lower(company) = ...` — no index on either column ([jobs.py:21-24](backend/app/routes/jobs.py:21)).
- 🟠 `trends.py` does `GROUP BY title` and `GROUP BY company` ([trends.py:52-53](backend/app/routes/trends.py:52), [trends.py:69-70](backend/app/routes/trends.py:69)) and `unnest(skills)` three separate times across `/trends/skills`, `/trends/skills/history` — no GIN index on the `skills` array column, no btree on `title`/`company`.
- Fine at current row counts; will degrade as ingestion volume grows in P1. Since Alembic doesn't exist yet (§5), these can't be added as a migration today — flagging so they're the first indexes added once Alembic lands.

## 5. No Alembic — tables still created via lifespan (P0's primary deliverable)

[main.py:19-21](backend/app/main.py:19): `await conn.run_sync(Base.metadata.create_all)` on every startup. CLAUDE.md requires this be replaced with a baselined Alembic setup before any schema change ships. This is the main structural item P0 asks for — not a bug to patch, the actual P0 task. Needs Railway DB access to snapshot + rehearse against a prod copy before cutover; I don't have that access from here, so this needs Amaan directly (see §8).

## 6. Dependency / tooling problems

- 🟠 **`backend/requirements.txt` exists** ([backend/requirements.txt](backend/requirements.txt)) alongside `pyproject.toml`/`uv.lock`. CLAUDE.md: *"never add a requirements.txt."* It's dead (nothing installs from it — Dockerfile and README both use `uv sync`) and it's already drifted from `pyproject.toml` (missing `beautifulsoup4`, `lxml`, `apscheduler`, which `pyproject.toml` has). Safe to delete now — see §7.
- 🔴 **`npm run lint` is broken.** [package.json:9](frontend/package.json:9) runs `eslint src --ext ts,tsx …` with `eslint@^9.11.1`, but there is no `eslint.config.js` (ESLint 9's flat config, which is mandatory by default — `.eslintrc.*` is no longer auto-loaded) and no `.eslintrc.*` either. Running lint today fails immediately with "couldn't find a configuration file." Since CI doesn't exist yet either, this has presumably been silently broken with nobody noticing. Safe, contained fix — see §7.
- ⚪ No `ruff`/`mypy` config anywhere in `pyproject.toml` despite CLAUDE.md's working-convention of "ruff + mypy clean." Nothing to audit yet since neither has been run/configured — tracked as a P0 CI item, not a pre-existing violation.
- ⚪ No CI at all — no `.github/workflows/`. `make eval-*` targets, ruff/mypy/pytest-in-CI, and the 10-item smoke eval are all P0 deliverables that don't exist yet.
- ⚪ No `eval/` directory, no `sources/companies.yaml`, no Alembic, no `taxonomy/skills.yaml` — all correctly absent, since none of these exist until P0 (Alembic/eval scaffolding) or P1 (sources/taxonomy). Listed here only to confirm the audit checked for them.

## 7. Error handling gaps

- 🟠 [scraper.py:59-73](backend/app/services/scraper.py:59) (`services/scraper.py`, the description fetcher) retries on 429 but on any other non-200 just logs and returns `""` — silently degrades to an empty description (and therefore zero extracted skills) with no signal surfaced anywhere that the row is incomplete. A job with a broken source page silently becomes a permanently skill-less row.
- 🟠 [linkedin.py:109](backend/scraper/linkedin.py:109) `resp.raise_for_status()` on the *listing* page (not the detail page) is unguarded — a transient 403/500 from LinkedIn propagates all the way up through `run_scrape` into the route handler, which has no try/except, so `POST /scrape` returns a bare 500 with no useful body to the caller and no structured log beyond the stack trace.
- ⚪ `POST /scrape/bulk`'s background task ([scrape.py:47-57](backend/app/routes/scrape.py:47)) does catch per-keyword exceptions and log them — this one's fine, flagging the contrast because the synchronous `/scrape` path doesn't have the same protection.

## 8. Doc drift

- 🟡 `README.md` still describes this as the **"Vancouver Job Analyzer"** scraping only LinkedIn, no mention of visa intelligence, multi-user, or the target architecture — entirely pre-CLAUDE.md-spec. Not a bug, but it's the first thing a new contributor (or future Amaan) reads and it's now actively misleading about what the product is. Worth a rewrite once P1 sources land rather than now, since it'll need to change again immediately.
- ⚪ **`CLAUDE.md` is itself listed in `.gitignore`** ([.gitignore:27](.gitignore:27)) and confirmed untracked (`git status --ignored` shows it as ignored, not committed) — despite this file's own header claiming it's "checked into the codebase." Worth a decision: if it's meant to be the source of truth for the project (which P0-P7 phase tracking implies), it probably should be tracked so its history/edits are visible in git like any other planning doc; if the intent is genuinely to keep it local-only, the header comment is just inaccurate. Flagging for Amaan's call, not fixing unilaterally since it's a deliberate-looking gitignore entry.

## 9. Things that are already in good shape (confirmed, not just assumed)

- Tailwind is already wired into the frontend ([tailwind.config.js](frontend/tailwind.config.js), used throughout `App.tsx` and all chart components) — P4's "add Tailwind" is partially done already; only shadcn/ui and dark mode remain.
- `skills` normalization to lowercase is correctly enforced in the one path that matters today, `services/nlp.py` — the gap is only the bypass via `POST /jobs` noted in §1.
- Async DB access is consistently async throughout — no sync SQLAlchemy calls found anywhere.
- `on_conflict_do_nothing` upsert on `source_url` is used correctly and consistently as the dedup mechanism ([scraper.py:91-95](backend/app/services/scraper.py:91)).
- Existing test suite (8 NLP unit tests + 8 API smoke tests) is real and reasonably targeted, just not wired into CI yet.
- `.env` is correctly gitignored; no secrets found committed anywhere in the repo.

---

## Recommended immediate action (small, safe, this session)

Per CLAUDE.md: *"Fix small, safe issues in dedicated PRs immediately; assign bigger findings to their relevant phase as tracked items."* I'd like sign-off to do these three now, each its own small commit:

1. Delete `backend/requirements.txt` (dead, contradicts the uv-only rule, already drifted from `pyproject.toml`).
2. Add a minimal `eslint.config.js` (flat config) so `npm run lint` actually runs.
3. Add an env flag (`ENABLE_LINKEDIN_SCRAPER`, default `false`) gating `scraper/linkedin.py` calls in both `scheduler.py` and `services/scraper.py`, and stop the scheduler auto-starting it — restores the CLAUDE.md contract ("gate behind a flag defaulting to off, stop scheduling it") without touching data or requiring DB access. **This one changes production behavior (scraping stops by default) — I want your explicit yes before I touch it, since it's outward-facing.**

Everything else above (auth on mutating routes, rate limiting, Alembic baseline + DB snapshot, indexes, CORS multi-origin, README rewrite) is bigger and gets tracked against the phase it belongs to (mostly P0 continuation and P1).

## Open decisions for Amaan

- Should `CLAUDE.md` be un-ignored and tracked in git?
- OK to ship the three small fixes above now (items 1–2 are inert; item 3 changes live scraping behavior)?
- For the Alembic baseline + prod DB snapshot (§5): I don't have Railway/DB credentials from this environment. Do you want to run the snapshot yourself and hand me a connection string for a copy, or do it together?
- Minimal auth gate for the three mutating routes until Clerk lands in P3 — shared-secret header good enough for now, or do you want to pull Clerk forward?
