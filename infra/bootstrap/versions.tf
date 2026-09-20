terraform {
  required_version = ">= 1.14"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Deliberately local state. This stack creates the bucket every *other*
  # stack stores its state in, so it cannot store its own state there without
  # a chicken-and-egg problem. The local state file is disposable and
  # gitignored — see infra/README.md for the two `terraform import` commands
  # that rebuild it from the live bucket.
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Stack     = "bootstrap"
    }
  }
}
