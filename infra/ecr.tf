# One repository, holding the backend image that both the Lambda API and the
# scheduled Fargate tasks run (phases 3 and 5). Same image, different entry
# commands — one build to keep in sync, and one set of layers to store.

resource "aws_ecr_repository" "backend" {
  name = "${var.project}-backend"

  # Mutable so `latest` can follow main. Deploys still reference the immutable
  # <git-sha> tag; `latest` is a convenience for local pulls.
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name

  # Rules are evaluated in priority order and an image matches at most one.
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after ${var.ecr_untagged_expiry_days} day(s)"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = var.ecr_untagged_expiry_days
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep the ${var.ecr_tagged_image_count} most recent images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.ecr_tagged_image_count
        }
        action = { type = "expire" }
      },
    ]
  })
}
