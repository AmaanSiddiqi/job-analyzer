output "vpc_id" {
  description = "App VPC."
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "Subnets for Fargate tasks (phase 3) and the RDS subnet group (phase 2)."
  value       = aws_subnet.public[*].id
}

output "ecr_repository_url" {
  description = "Push target for the backend image."
  value       = aws_ecr_repository.backend.repository_url
}

output "github_deploy_role_arn" {
  description = "Set this as the repository variable AWS_DEPLOY_ROLE_ARN (see infra/README.md) — it is not committed, because it contains the account id and this repo is public."
  value       = aws_iam_role.github_deploy.arn
}
