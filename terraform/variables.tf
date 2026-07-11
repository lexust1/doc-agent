# The AWS region where resources will be deployed
variable "aws_region" {
  description = "AWS region"
  default     = "us-east-1"
}

# SSH key pair name for accessing the EC2 instance (optional)
variable "key_name" {
  description = "Name of an existing EC2 key pair (for SSH access, optional)"
  type        = string
  default     = ""   # leave empty if you don't need SSH
}

# Endpoint for the Qdrant vector database
variable "qdrant_url" {
  description = "URL of the Qdrant instance (e.g., http://your.qdrant.host:6333 or Qdrant Cloud URL)"
  type        = string
}

# The specific Qdrant collection to query for documents
variable "collection_name" {
  description = "Qdrant collection name"
  default     = "pue_chunks"
}

# API key for the LLM (marked sensitive to hide its value from console output/logs)
variable "nanogpt_api_key" {
  description = "API key for the LLM provider"
  type        = string
  sensitive   = true
}

# The base URL endpoint for the LLM API provider
variable "nanogpt_base_url" {
  description = "Base URL for the LLM API"
  type        = string
}

# Security restriction: Defines which specific IP address is allowed to access the Streamlit UI
variable "allowed_cidr" {
  description = "Your public IP in CIDR format (e.g., 203.0.113.45/32). Only this IP can access the Streamlit UI."
  type        = string
}