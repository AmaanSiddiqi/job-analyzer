# infra/ — Terraform for the AWS migration (P1.4)

The plan, the costs and the reasoning live in [`AWS.md`](../AWS.md). This file
is the operator's manual for the code in this directory.

**Phase 1 scope (this PR):** remote state, VPC, ECR, and the GitHub Actions
OIDC role. Nothing here serves traffic, stores data, or runs a job — the live
site is still Railway, and stays there until phase 5's cutover.

## Layout

| Path | What it is |
|---|---|
| `bootstrap/` | The S3 bucket every other stack keeps its state in. Local state, applied once. |
| `versions.tf` | Terraform and provider pins; the partial S3 backend block. |
| `vpc.tf` | VPC, two public subnets, IGW, free S3 gateway endpoint. No NAT — see AWS.md. |
| `ecr.tf` | `landed-backend` repository plus a lifecycle policy that stops old layers accumulating. |
| `github_oidc.tf` | The OIDC provider and the role `.github/workflows/deploy.yml` assumes. |
| `terraform.tfvars` | Project name, region, and the repo allowed to deploy. No secrets. |

## First run, from a fresh clone

```bash
brew install hashicorp/tap/terraform
make tf-bootstrap   # once per AWS account: creates the state bucket
make tf-init        # writes infra/backend.hcl from your account id, then inits
make tf-plan
make tf-apply
```

`infra/backend.hcl` is generated rather than committed: the bucket name
embeds the AWS account id and this repository is public. `make tf-init`
recomputes the same name from `aws sts get-caller-identity`, so a fresh clone
needs no hand-copied values.

## Wiring up the deploy

`terraform apply` prints `github_deploy_role_arn`. Set it as a repository
**variable** (not a secret — it is an identifier, and a secret would be masked
out of every log where you want to read it):

```bash
gh variable set AWS_DEPLOY_ROLE_ARN --body "$(cd infra && terraform output -raw github_deploy_role_arn)"
```

`.github/workflows/deploy.yml` skips itself while that variable is unset, so
main stays green before the bootstrap and on forks.

## Things worth knowing before you change something here

**There are no AWS access keys, and that is the point.** GitHub Actions
assumes `landed-github-deploy` through OIDC; the trust policy admits exactly
`repo:AmaanSiddiqi/job-analyzer:ref:refs/heads/main`. Widening
`github_deploy_refs` to include pull requests would let a fork's PR push an
image to production ECR — don't, without a separate, read-only role.

**No DynamoDB lock table**, though AWS.md phase 1 mentions one. The S3
backend's `dynamodb_table` argument was deprecated in Terraform 1.11 and
removed in 1.14; locking is native to S3 now (`use_lockfile = true`), so the
table would be a resource nothing reads.

**The bootstrap state is disposable.** If `infra/bootstrap/terraform.tfstate`
is lost, rebuild it rather than recreating the bucket:

```bash
cd infra/bootstrap
terraform init
terraform import aws_s3_bucket.state "landed-tfstate-$(aws sts get-caller-identity --query Account --output text)"
terraform plan   # should show only the sub-resources, which re-import or re-apply harmlessly
```

The bucket carries `prevent_destroy`, so a stray `terraform destroy` fails
loudly instead of taking the state with it.

**CI validates but never applies.** The `terraform` job in `ci.yml` runs
`fmt -check` and `validate -backend=false`, which need no credentials. Applies
are deliberately manual and local while the stack is small enough that a human
reading a plan is better than a pipeline approving itself.
