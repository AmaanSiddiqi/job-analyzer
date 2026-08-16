# P0 Phase Report — Audit & Foundations

**Closed:** 2026-08-16 · **PRs:** #1–#4, all merged to `main` and live in production
**DoD per CLAUDE.md:** `AUDIT.md` reviewed by Amaan ✅ · `make eval-*` runs end-to-end on draft labels ✅ · migrations rehearsed on a prod copy ✅

## What shipped

| Deliverable | Where | State |
|---|---|---|
| Codebase audit | `AUDIT.md` | All findings closed or phase-assigned |
| Alembic (baseline + deploy step) | `backend/alembic/`, `railway.toml` | Live — prod at rev `0002` |
| CI | `.github/workflows/ci.yml` | Green on every PR since #2 |
| Eval harness + gold set | `backend/eval/`, `Makefile` | 150 listings, 40 human-verified |
| Baseline extraction numbers | `reports/extraction_eval.md` | P 0.874 / R 0.312 / F1 0.460 |
| Auth + rate limiting | `app/auth.py`, `app/rate_limit.py` | Verified live in prod (401/429/503) |
| DB indexes | migration `0002` | Applied to prod via deploy pipeline |
| LinkedIn scraper deprecation | `ENABLE_LINKEDIN_SCRAPER` flag, default off | Scraping intentionally stopped |

## Key numbers

- **Corpus:** 5,862 listings, 1,847 companies (frozen — last scrape 2026-08-11, no new data until P1 sources land).
- **Baseline extractor** (spaCy PhraseMatcher, ~200-term vocab) vs. 150-listing gold set:
  micro **precision 0.874, recall 0.312, F1 0.460**. High precision, low recall:
  it rarely invents skills but misses ~69% of real ones — modern AI/ML terms
  (`llms`, `rag`, `prompt engineering`), specific tools (`dynatrace`, `figma`),
  and entire non-engineering domains are invisible to it. **This is the bar P1's
  LLM extractor must beat, especially on recall.**
- **Gold-set honesty:** 40/150 rows `human_verified` (seeded random sample of the
  disagreement queue); 108 unreviewed disagreements and 2 auto-accepted agreements
  are labeled as such per-row via `verification_method`. 148/150 listings disagreed
  with baseline — expected given the vocab gap, but it means the "mandatory review
  on disagreement" policy from CLAUDE.md doesn't bound review time when baseline is
  weak; `review_cli.py --sample-size` exists for exactly this.

## Notable incidents & lessons (worth remembering)

1. **The Alembic deploy step would have crashed the first deploy.** `upgrade head`
   against the already-populated, never-Alembic-managed prod table fails with
   `DuplicateTableError`. Caught in rehearsal against a restored prod snapshot;
   fixed with a one-time `alembic stamp head` on prod. Lesson: always rehearse
   migrations against a prod copy — the rehearsal caught exactly the class of bug
   it exists to catch.
2. **Prod Postgres is 18.4, not 16** as the docs claimed. Discovered because
   `pg_dump` 16 refuses to talk to an 18 server. Docs and docker-compose corrected.
3. **PR #3 was stacked on PR #2 and merged into the wrong base** — its merge landed
   on the `p0/ci` branch, not `main`, and had to be merged forward manually.
   Lesson: with stacked PRs, merge in order, or re-target before merging.
4. **`npm run lint` had been silently broken** (ESLint 9 requires flat config;
   none existed) — invisible because there was no CI. First real lint run surfaced
   a legitimate hook-dependency issue in `App.tsx`.
5. **Ruff/mypy first runs found two real bugs** in working code: a `zip()` that
   could silently misalign scraped listings with descriptions, and SQL `count`
   labels shadowing `tuple.count()` on SQLAlchemy rows.
6. **Railway's table-formatted variable output truncates values** — an admin key
   copied from it failed auth confusingly. Use `railway variables --json`.

## Decisions made (do not relitigate without cause)

- Live LinkedIn auto-scraping **stays off** until P1 sources replace it (Amaan
  approved; matches CLAUDE.md's deprecation mandate).
- uv remains the single Python dependency story; no `requirements.txt` mirror.
- Shared-secret header auth is the interim gate; Clerk stays in P3 (not pulled
  forward).
- `ruff format` is **not** enforced in CI (only `ruff check`) — avoided an
  unrelated whole-repo reformat; revisit if formatting drift becomes a problem.
- GIN index on `skills` was added for P5's future containment queries and
  documented as *not* helping today's unfiltered trend aggregates — kept honest.

## Carried forward

| Item | Phase | Note |
|---|---|---|
| Replace LinkedIn with board-JSON/Adzuna/Jooble sources | **P1** | Corpus is frozen until this lands |
| LLM extraction pipeline + visa signals + cost caps + dead-letters | **P1** | Eval baseline ready to compare against |
| `sources/companies.yaml` (~100 Canadian boards) | **P1** | Amaan reviews the list |
| `taxonomy/skills.yaml` seeded from `_SKILLS_VOCAB` | **P1** | Cap ~200, alias map |
| README rewrite (still describes the pre-product analyzer) | **P1** | Deferred deliberately — it would change again immediately |
| CORS: single-origin env var, no Vercel preview support | P4-ish | AUDIT.md §2, minor |
| In-process APScheduler has no distributed lock | P1 | Moot once Arq workers replace it |
| Non-concurrent `CREATE INDEX` in migrations | When table grows | Noted in `0002`'s docstring |
| Clerk auth replaces the shared-secret gate | P3 | |

## Production state at phase close

- API `https://api.amaansiddiqi.me` — healthy, Alembic rev `0002`, all indexes live.
- Frontend `https://jobs.amaansiddiqi.me` — unchanged UX except scrape buttons now
  prompt for the admin key (once per browser session).
- Railway env: `ADMIN_API_KEY` set; `ENABLE_LINKEDIN_SCRAPER` unset (off);
  `ANTHROPIC_API_KEY` **not** set in Railway (eval-only, lives in local `.env`).
- Data: 5,862 listings / 1,847 companies, frozen.
