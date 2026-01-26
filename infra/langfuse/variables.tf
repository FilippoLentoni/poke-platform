variable "domain" {
  type        = string
  description = "Domain name for the Langfuse deployment (e.g., langfuse.poketrader.ai)."
  default     = "langfuse.poketrader.ai"
}

variable "name" {
  type        = string
  description = "Optional installation name to avoid collisions."
  default     = "langfuse"
}

variable "aws_region" {
  type        = string
  description = "AWS region for Langfuse deployment."
  default     = "us-east-1"
}
