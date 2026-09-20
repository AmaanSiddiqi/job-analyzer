.PHONY: eval-smoke eval-export eval-draft eval-review eval-extraction test lint \
	tf-bootstrap tf-init tf-plan tf-apply tf-fmt tf-validate

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
# the accept/edit/skip/quit keys. Pass SAMPLE_SIZE=N to cap the manual queue
# (e.g. `make eval-review SAMPLE_SIZE=40`) — worth reading the script's
# docstring on why this matters in practice before running without it.
eval-review:
	cd backend && uv run python -m eval.scripts.review_cli \
		--in eval/gold/extraction_skills.draft.jsonl \
		--out eval/gold/extraction_skills.jsonl \
		$(if $(SAMPLE_SIZE),--sample-size $(SAMPLE_SIZE),)

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

# --- infrastructure (see infra/README.md and AWS.md) ---

# One-time: create the S3 bucket the main stack stores its state in. Local
# state, gitignored, disposable — infra/README.md has the re-import commands.
tf-bootstrap:
	cd infra/bootstrap && terraform init && terraform apply

# Generate the gitignored backend config from the caller's own AWS account and
# initialise the main stack. Safe to re-run; this is step one from a fresh
# clone, since the bucket name is not committed (public repo).
tf-init:
	@command -v terraform >/dev/null || { echo "terraform not installed: brew install hashicorp/tap/terraform"; exit 1; }
	@account=$$(aws sts get-caller-identity --query Account --output text) && \
		project=$$(awk -F'"' '/^project/ {print $$2}' infra/terraform.tfvars) && \
		region=$$(awk -F'"' '/^region/ {print $$2}' infra/terraform.tfvars) && \
		printf 'bucket = "%s-tfstate-%s"\nregion = "%s"\n' "$$project" "$$account" "$$region" > infra/backend.hcl && \
		echo "wrote infra/backend.hcl for account $$account ($$region)"
	cd infra && terraform init -backend-config=backend.hcl -reconfigure

tf-plan:
	cd infra && terraform plan

tf-apply:
	cd infra && terraform apply

# What CI checks — no AWS credentials required.
tf-fmt:
	terraform fmt -recursive -check -diff infra

tf-validate:
	cd infra && terraform init -backend=false -input=false && terraform validate
	cd infra/bootstrap && terraform init -backend=false -input=false && terraform validate
