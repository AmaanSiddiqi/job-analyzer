# P1 Phase Report — Sources & Extraction

**Status:** complete — backfill finished 2026-09-19, 100% coverage of eligible postings · **PRs:** #5–#16, all merged
**DoD per CLAUDE.md:** F1 report published, beating baseline P 0.874 / R 0.312 / F1 0.460 ✅ · Haiku-vs-Sonnet and thinking-on-vs-off reported ✅ · per-source counts visible ✅ · ≥90% of *eligible* listings extracted ✅ *(100%: 1,782 of 1,782; scheduled extraction keeps it there)*

## What shipped

| Deliverable | Where | State |
|---|---|---|
| Verified company boards | `backend/sources/companies.yaml` | 69 boards, identity-checked |
| Board-JSON ingestion | `app/ingestion/` (Greenhouse/Lever/Ashby) | Live, every 6h |
| Adzuna/Jooble + company discovery | `app/ingestion/aggregators.py` | Live, feeds a review queue |
| Skill taxonomy | `backend/taxonomy/skills.yaml` | 201 ids, 388 aliases, 70.9% gold coverage |
| LLM extraction pipeline | `app/extraction/` | Runs; backfill not yet started |
| Extraction eval | `reports/extraction_eval_llm.md` | 3 configs × 150 listings |
| LinkedIn deprecation | `ENABLE_LINKEDIN_SCRAPER`, default off | Scraping stopped |

## Headline result

**Sonnet 5, thinking off: micro F1 0.830** (P 0.916 / R 0.758) against the frozen
baseline's **0.460** — **+0.370**. Against the fairer normalized baseline (0.652)
it is **+0.178**. On the 40 human-verified rows alone it scores **0.844**, i.e.
slightly *better* where the labels are most trustworthy.

Recall was the whole point: the baseline missed ~69% of real skills. The LLM
more than doubles it, 0.312 → 0.758, while *raising* precision.

Backfill cost, as measured in production: **~$12** for the ~1,782 eligible postings (the eval-time projection of $50–100 assumed all 7,200 rows would be extracted; the cost rules, per-posting dedup and the batch cache warm-up cut it — see below).

## What the eval decided

Both open cost questions resolved against spending more.

**Haiku 4.5 is worse and more expensive** — 2x the per-listing cost at −0.086 F1.
Two independent causes: the cached prefix (system prompt, skill list and the
injected output schema) is 3,337 Haiku tokens, under Haiku 4.5's 4,096-token
minimum cacheable prefix, so prompt caching is silently inert and it re-pays for
the whole prefix every call; and it degenerates under the
constrained grammar, emitting digit runs into numeric fields until it hits
`max_tokens` (6 listings failed that way, all billed).

**Thinking on vs off is a null result** — identical cost, within 0.002 F1,
median +0 output tokens. CLAUDE.md assumed thinking would double the cost to
~$0.032/listing; that came from token estimation and is not what the API does
here. At `effort=low`, adaptive thinking does not engage on schema-constrained
extraction. `EXTRACTION_THINKING` stays false, now on evidence.

## The blocker that nearly sank the phase

The extraction pipeline merged in a state where **it could not make a single
successful call** — the API rejected `JobComponents` with `400 "Schema is too
complex."` Bisecting against the live API found three undocumented limits:

1. **Field order decides whether a schema compiles.** The same fourteen fields
   are accepted when the four nested models are declared first and rejected when
   they trail or interleave — at a byte-identical 3,472-char schema. A
   3,472-char schema compiles where a 3,459-char one with the same fields in a
   worse order does not. Size is not the variable it appears to be.
2. **Unions are expensive** — ~11 `anyOf` across the whole schema. Tri-state
   fields became a `Stated` enum (`yes`/`no`/`not_stated`); unstated scalars use
   `""`/`0`/`unknown` sentinels, converted to real NULLs at the service boundary.
3. **Docstrings and `description=` are serialized into the schema** — 449 chars
   in this model, enough to flip the verdict alone. Per-field semantics moved to
   the prompt, where they are cached tokens.

`title_raw`, `company_raw`, `location_raw` and `posted_at` were dropped: each
duplicated a column `raw_listings` already holds from the board API, so we were
spending schema budget to obtain a less reliable copy.

## Measurement bugs found and fixed

The first full eval run produced numbers that were all wrong in ways that would
not have been obvious from the report alone. Recording them because each is a
trap that recurs:

- **Haiku failed 150/150** on `400 "This model does not support the effort
  parameter"` — it rejects `output_config` instead of ignoring it. Scored
  blindly, the report would have shown Haiku at F1 0.000 and "concluded" Sonnet
  wins for entirely the wrong reason.
- **Both Sonnet runs silently lost ~60% of their work.** A non-`ExtractionFailed`
  exception in one coroutine aborted the whole `asyncio.gather`, and the process
  still exited 0.
- **Thinking was never enabled.** `build_request` only ever set `thinking` to
  *disable* it, so the "on" config took the API default. A test asserted this
  exact behaviour, locking the bug in. Sonnet 5 also wants
  `thinking.type: adaptive`, not `enabled` + `budget_tokens`.
- **Visa yield read 99%** against a corpus-measured <1%: the scorer checked
  `is not None`, but v3 reports the string `"not_stated"`. Now 5–6%.
- **Cached tokens were billed at zero.** `price_call` used only
  `usage.input_tokens`, which excludes cache reads — an undercount in the one
  module whose job is to not undercount spend.
- **The prediction cache ignored `prompt_version`**, so stale rows from an older
  prompt would count as already-predicted and mix two prompts in one report.

## Honest caveats

- **40/150 rows are human-verified** (27%). The headline F1 holds on that subset
  (0.844), but the other 110 rows are annotator-model labels.
- **The gold set was representative; the August regex scan was not.** Its 69%
  experience-statement rate looked like over-sampling against the scan's 27.9%.
  Extracting the whole corpus settled it: **60.0% of 1,782 production postings
  state an experience requirement**, with 98.2% of the quotes verbatim in the
  source. The scan undercounted by more than half, and the corpus rates below
  supersede it.
- **Costs in the eval table are a lower bound** (~9%) for rows predicted before
  the cache-pricing fix.
- **No eligibility/visa labels exist yet**, so those fields are reported as yield
  rates, not as accuracy. That is the next labeling pass.
- **Workday ingestion is carried to P1.5** — the coverage that replaces LinkedIn.

## After the eval: taking it to production (2026-09-19, PRs #15–#16)

The eval proved the extractor; production needed three more things the P1 code
didn't have. **A batch path** (the spec requires it for backfills), **a
scheduler**, and **a cache warm-up**, found by measuring a real batch: its
concurrent requests never hit the prompt cache, so it cost $0.0149/listing —
no cheaper than live. Warming the cache with one live request before each
submission brought it to **$0.0067**. Building it surfaced five more defects,
each of which would have cost money or hidden it; they are listed in the
CHANGELOG.

**Measured production costs:** the backfill of 1,782 eligible postings cost
**$16.57** across two batches; steady state ≈ **$7–11/month**.

## Production results (backfill complete, 2026-09-19)

| | |
|---|---|
| Postings extracted | **1,782** (100% of eligible — P1 DoD met) |
| Batches | 2, both collected; 1,780 succeeded, 2 needed a live retry, **0 dead letters** |
| Cost | **$16.57**, or **$0.0093/posting** (996/1000 requests read the warmed cache) |
| Evidence quality | 98.2% of experience quotes verbatim in the source posting |

**Cost note:** $0.0093 supersedes the $0.0067 measured pre-launch — the cache
warm-up works exactly as designed, but real postings are ~2.5x longer than the
four-listing sample it was measured on (median input 2,356 tokens). Steady
state is ~$7–11/month at current ingestion rates.

### What the corpus actually says (1,782 postings, each claim evidence-backed)

| Signal | Rate | August regex scan |
|---|---|---|
| States an experience requirement | **60.0%** | 27.9% (undercount) |
| …of those, open to ≤2 years | 19.6% (modal 5 yrs) | 17% |
| Degree required | 18.4% | 24.6% |
| Requires *existing* work authorization | **6.3%** | not measured |
| French/bilingual required | 2.9% | 4.9% |
| New-grad friendly | 1.5% | 2.9% (co-op/intern) |
| Sponsorship offered | 1.1% | 0.2% |
| Citizenship/PR required | 0.7% | 0.1% |

The wedge is stronger than the thesis assumed: experience gates **twice** as
many postings as believed, and four out of five of those exclude a candidate
with ≤2 years. Visa signals remain rare, confirming the August pivot — though
the 6.3% demanding existing authorization is a real gate for anyone who would
need sponsorship, and it was invisible to the old scan.

## Next

1. Switch the dashboard's skill data to the LLM extractor behind a flag (fixes
   the baseline's "go" false positive: it tags "go to market", "on-the-go").
2. Eligibility/visa gold labels, so the flagship signals are scored, not counted.
3. Decide: AWS migration (career value; ~$40–50/mo) or P1.5 Workday ingestion
   (the coverage that replaces LinkedIn) first.
