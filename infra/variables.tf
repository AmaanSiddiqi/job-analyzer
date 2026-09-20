variable "project" {
  description = "Name prefix for every resource in the account."
  type        = string
  default     = "landed"
}

variable "region" {
  description = "AWS region. ca-central-1 (Montreal) keeps P3's resumes and work-authorization data in Canada — see AWS.md."
  type        = string
  default     = "ca-central-1"
}

variable "vpc_cidr" {
  description = "CIDR for the app VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "Number of availability zones to spread public subnets across. Two is the minimum an RDS subnet group accepts (phase 2)."
  type        = number
  default     = 2

  validation {
    condition     = var.az_count >= 2 && var.az_count <= 3
    error_message = "az_count must be between 2 and 3."
  }
}

variable "github_owner" {
  description = "GitHub account that owns the deploying repository."
  type        = string
  default     = "AmaanSiddiqi"
}

variable "github_repo" {
  description = "Repository allowed to assume the deploy role via OIDC."
  type        = string
  default     = "job-analyzer"
}

variable "github_deploy_refs" {
  description = <<-EOT
    Workflow subjects allowed to assume the deploy role, appended to
    `repo:<owner>/<repo>:`. Defaults to merges on main only — a pull request
    from a fork must never be able to push an image to production ECR.
  EOT
  type        = list(string)
  default     = ["ref:refs/heads/main"]
}

variable "ecr_untagged_expiry_days" {
  description = "Days before an untagged image layer is expired. Untagged images are replaced tags from a redeploy — dead weight at $0.10/GB/month."
  type        = number
  default     = 1
}

variable "ecr_tagged_image_count" {
  description = "Number of tagged images to retain. Ten is several weeks of deploys and keeps a rollback target."
  type        = number
  default     = 10
}
