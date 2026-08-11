.PHONY: eval-smoke eval-export eval-draft eval-review eval-extraction test lint

# --- eval targets (see backend/eval/README.md for the full protocol) ---

# No DB, no API key, no network — 10 hand-authored fixtures. Wired into CI.
eval-smoke:
	cd backend && uv run python -m eval.scripts.score_extraction \
		--gold eval/fixtures/smoke_listings.jsonl \
		--report ../reports/extraction_eval_smoke.md

# Pull a random sample of real listings from the DB (DATABASE_URL) into the
# labeling pool. Read-only.
eval-export:
	cd backend && uv run python -m eval.scripts.export_listings \
		--limit 150 --out eval/gold/listings_pool.jsonl

# Draft-label the pool with a stronger annotator model. Requires
# ANTHROPIC_API_KEY and `uv sync --extra eval`.
eval-draft:
	cd backend && uv run python -m eval.scripts.draft_label \
		--in eval/gold/listings_pool.jsonl \
		--out eval/gold/extraction_skills.draft.jsonl

# Interactive keyboard-driven review — resumable, see script docstring for
# the accept/edit/skip/quit keys.
eval-review:
	cd backend && uv run python -m eval.scripts.review_cli \
		--in eval/gold/extraction_skills.draft.jsonl \
		--out eval/gold/extraction_skills.jsonl

# Score baseline_extractor against the real, human-reviewed gold set.
eval-extraction:
	cd backend && uv run python -m eval.scripts.score_extraction \
		--gold eval/gold/extraction_skills.jsonl \
		--report ../reports/extraction_eval.md

# --- convenience wrappers around what CI runs ---

test:
	cd backend && uv run pytest tests/ -v

lint:
	cd backend && uv run ruff check . && uv run mypy .
	cd frontend && npm run lint
