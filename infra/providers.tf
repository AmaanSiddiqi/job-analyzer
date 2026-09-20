provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Stack     = "main"
    }
  }
}

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}
