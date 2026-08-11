# Eval harness

Machine-assisted labeling + scoring, per CLAUDE.md's Evaluation & product
metrics section. Today this covers **extraction** only (the one thing that
exists — `app.services.nlp.extract_skills`, CLAUDE.md's frozen
`baseline_extractor`). Dedup (P2) and matching (P5) evals will land later,
following the same file-per-task / `human_verified`-per-record conventions
established here — see `eval/schemas.py`'s module docstring.

## Protocol

1. **Export** a random sample of real listings from the DB into a labeling
   pool (`eval/gold/listings_pool.jsonl`).
2. **Draft-label** the pool with a stronger annotator model (Claude — a
   different model from the production extractor by construction, since the
   production extractor is spaCy PhraseMatcher, not an LLM at all). Also
   computes `baseline_extractor`'s output for the same listings and flags
   where the two disagree.
3. **Review**: a keyboard-driven CLI shows every disagreement (mandatory)
   plus a random 25% audit sample of agreements; everything else auto-accepts
   the annotator's draft. Every row in the final gold set carries
   `human_verified` + `verification_method` so published numbers stay honest
   about what a human actually looked at.
4. **Score**: per-listing set-based P/R/F1 for `skills`, aggregated micro and
   macro, rendered to `reports/extraction_eval.md`.

Target: ~150 listings, under 2 hours of human review time total (the 25%
audit + mandatory-disagreement-only policy is what keeps it under budget).

## Commands

```bash
# 1. Pull a fresh sample from the DB (needs DATABASE_URL)
make eval-export

# 2. Draft-label with Claude (needs ANTHROPIC_API_KEY, `uv sync --extra eval`)
make eval-draft

# 3. Review interactively — resumable across sittings
make eval-review

# 4. Score baseline_extractor against the reviewed gold set
make eval-extraction

# CI-safe smoke test — 10 hand-authored fixtures, no DB, no API key, no network
make eval-smoke
```

## Files

```
eval/
  schemas.py            # PoolListing, DraftExtractionLabel, GoldExtractionLabel
  jsonl.py               # tiny JSONL read/write helpers
  fixtures/
    smoke_listings.jsonl # 10 hand-authored listings for CI — never touches this dir from eval-export/draft/review
  gold/
    listings_pool.jsonl          # gitignored — regenerate via eval-export
    extraction_skills.draft.jsonl # gitignored — regenerate via eval-draft
    extraction_skills.jsonl       # tracked — the actual reviewed gold set, once built
  scripts/
    export_listings.py
    draft_label.py
    review_cli.py
    score_extraction.py
```

## Status

Harness built and smoke-tested end-to-end (`make eval-smoke` runs in CI on
every push/PR). The real 150-listing gold set has not been built yet — that
needs `ANTHROPIC_API_KEY` for the draft-labeling step and ~2 hours of Amaan's
time for review. Once it exists, `reports/extraction_eval.md` gives the real
baseline_extractor P/R/F1 numbers that P1's LLM extractor will need to beat.
