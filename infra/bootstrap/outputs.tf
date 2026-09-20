output "state_bucket" {
  description = "Bucket holding the main stack's remote state. Feed it to `terraform init -backend-config=`."
  value       = aws_s3_bucket.state.id
}

output "region" {
  description = "Region the state bucket lives in."
  value       = var.region
}
