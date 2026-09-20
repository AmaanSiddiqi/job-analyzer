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
