# AWS migration plan (P1.4)

**Status:** approved 2026-09-20, not started. **Owner:** Amaan. **Estimate:** ~1 week in PR-sized pieces.

## Why this is happening

Not cost. Railway is $10–25/mo and works. This is a **career decision**, made deliberately: AWS, Terraform, CI/CD and Docker appear in most Canadian DevOps and platform postings, and the corpus agrees — across software/infrastructure roles in our own extracted data, `aws` ranks **2nd of all skills** (189 of ~1,000 postings) and **3rd among junior-open** ones (17 of 48), with `ci/cd`, `docker` and `kubernetes` close behind. Landed's own data is the argument for building Landed on AWS.

CLAUDE.md's standing rule is "don't migrate without a trigger (bill >$50/mo, Postgres >10GB, always-on compute Railway prices badly)". None of those fired. This is a fourth, explicitly recorded trigger, and the spec now says so.

**Secondary technical win:** RDS PostgreSQL supports `pgvector`, which P5's matching needs and which CLAUDE.md still flags as *unverified* on Railway. This migration resolves that dependency instead of discovering it late.

## Shape: the cheap build, not the textbook one

| Component | Choice | ~$/mo (ca-central-1) |
|---|---|---|
| API | **Lambda** container image (FastAPI via Mangum) + Function URL | $0–2 |
| Scheduled jobs | **EventBridge → ECS Fargate task** (ingestion 6h, extraction 45min) | ~$0.20 |
| Database | **RDS PostgreSQL `db.t4g.micro`**, single-AZ, 20 GB gp3 | ~$15 |
| Raw layer | **S3** — board JSON written before transform | ~$1 |
| Images | **ECR** | ~$0.20 |
| Monitoring | **CloudWatch** alarms + logs | ~$1 |
| **Total** | | **~$18** |

New accounts get up to **$200 in credits** (12-month expiry), so year one is effectively free.

**At signup, choose the PAID plan, not the Free plan.** Both grant the credits; the Free plan *closes the account automatically* after 6 months or when credits run out. For a live app that means the site goes dark.

### Deliberately not built

| Skipped | Saves | Why |
|---|---|---|
| ALB + always-on ECS service | ~$19/mo | Lambda serves this traffic. Fargate still runs the scheduled jobs, so "ECS Fargate" stays honest on the résumé. |
| NAT gateway | ~$33/mo | Public subnets + tight security groups; free S3 gateway endpoint. The single most common way a hobby AWS bill triples. |
| Multi-AZ RDS | ~$15/mo | Portfolio project; automated backups suffice. Revisit when real users' resumes land (P3). |
| Aurora Serverless v2 | — | Floors around $43/mo at minimum capacity. Worse than a t4g.micro for this. |
| Kubernetes | — | CLAUDE.md forbids it, and it would add cost and no story this project needs. |

**Region: `ca-central-1` (Montreal).** us-east-1 saves ~$2/mo — a rounding error against the LLM line. Montreal keeps P3's resumes and work-authorization data in Canada, which avoids a Quebec Law 25 transfer assessment and supports an honest "your data stays in Canada" claim. Note the limit of that claim: resumes are still *processed* by Claude outside Canada at P3; check the API's `inference_geo` options then.

## Phases (one PR each)

Each is independently mergeable and leaves production untouched until the final cutover.

### 1. Terraform skeleton + OIDC deploy
Remote state (S3 + DynamoDB lock), VPC with public subnets, ECR repo, GitHub Actions role assumed via **OIDC — no long-lived AWS keys in GitHub secrets**, and a workflow that builds and pushes the image on merge to `main`.
**DoD:** `terraform plan` clean from a fresh clone; a merge pushes an image to ECR; no AWS access keys exist anywhere.

### 2. RDS + migration rehearsal
`db.t4g.micro`, 20 GB gp3, automated backups, security group open only to the app. Restore a Railway dump into it and run `alembic upgrade head`. The database is **158 MB** today, growing ~100 MB/month (mostly `raw_listings`), so 20 GB is years of headroom.
**DoD:** a prod dump restores clean; row counts match; `SELECT * FROM pg_available_extensions WHERE name='vector'` confirms pgvector for P5.

### 3. Scheduled jobs on EventBridge + Fargate
One task definition, two rules: ingestion every 6h, extraction every 45min — replacing APScheduler. This also removes the in-process scheduler's single-instance constraint, the actual reason Arq+Redis was once considered.
**DoD:** both fire on schedule against the *new* database with the feature flags **off**, proving wiring without spending on extraction.

### 4. S3 raw layer
Board and aggregator responses are written to `s3://<bucket>/raw/<source>/<date>/<id>.json` before transform, then loaded into `raw_listings` as now. The raw/clean split means a parser fix can be replayed without re-fetching every board.
**DoD:** a run writes objects; a replay script rebuilds `raw_listings` rows from S3 alone.

### 5. Alarms + cutover
CloudWatch alarms on: a failed scheduled run, an ingestion run returning **zero rows** (the silent-failure case), extraction dead-letters rising, and an AWS Budgets alarm at $30/mo. Then the cutover.
**DoD:** an alarm fires on a deliberately broken run; the live site serves from AWS; Railway is off.

## Cutover checklist

The pipeline is live and spends money, so the order matters.

1. **Freeze**: set `ENABLE_BOARD_INGESTION`, `ENABLE_AGGREGATOR_INGESTION`, `ENABLE_LLM_EXTRACTION` to false on Railway. **Confirm no extraction batch is in flight** (`GET /admin/extraction-status` → `in_flight: 0`); an open batch collected by nobody is money paid for nothing.
2. **Final dump + restore** into RDS. Verify row counts and `alembic_version`.
3. **Secrets into AWS**: `ANTHROPIC_API_KEY`, `ADMIN_API_KEY`, `DATABASE_URL` in Secrets Manager or SSM Parameter Store — never in a task definition's plain environment.
4. **Flags on in AWS**, off on Railway. **Never both**: two schedulers means double ingestion and double extraction spend.
5. **DNS**: point `api.amaansiddiqi.me` at the Lambda Function URL (CloudFront or a custom domain mapping). Update `CORS_ORIGIN`; Vercel's frontend env needs no change if the hostname is preserved.
6. **Watch one full cycle**: an ingestion run and an extraction cycle end to end, with costs in `llm_usage` matching expectations.
7. **Rollback**: keep Railway deployed but flag-disabled for one week. Reverting is flags + DNS, since the database dump is point-in-time restorable.

## Post-migration follow-up

- Replace the static `ANTHROPIC_API_KEY` with **workload identity federation** from the ECS task role — production then holds no model credential at all. Federation supports AWS but not Railway, so this only becomes possible after the move.
- Prune `raw_listings`: 112 MB of the 158 MB is aggregator rows the pipeline never extracts from. With S3 as the raw archive, the table can hold only what the pipeline needs.

## What this buys on a résumé

> Deployed on AWS with Terraform (ECS Fargate, EventBridge, Lambda, S3, RDS); GitHub Actions runs 269 tests and deploys on merge via OIDC; CloudWatch alarms on failed or empty ingests.

Every clause is checkable in the repo, which is the point. The artifacts interviewers can actually probe — the Terraform, the pipeline, an alarm with a real incident behind it — are what the money is buying. Region and instance size are invisible to them, which is exactly why this plan spends nothing on them.
