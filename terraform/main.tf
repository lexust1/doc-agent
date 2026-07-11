# Configure Terraform to require the AWS provider (version 5.x)
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Set the AWS provider region using our variable
provider "aws" {
  region = var.aws_region
}

# Fetch the current AWS account details (used for building the ECR login URL)
data "aws_caller_identity" "current" {}

# Create an Elastic Container Registry (ECR) repository to store the Streamlit Docker image
resource "aws_ecr_repository" "streamlit" {
  name                 = "doc-agent-streamlit"
  image_tag_mutability = "MUTABLE"

  # Automatically scan images for vulnerabilities when pushed
  image_scanning_configuration {
    scan_on_push = true
  }
}

# Output the repository URL so you can use it in your local Docker build/push commands
output "ecr_repository_url" {
  value = aws_ecr_repository.streamlit.repository_url
}

output "pipeline_run_command" {
  value = <<EOT
docker run --rm --network host \
  -e DEPLOYMENT_MODE=aws \
  -e AWS_REGION=${var.aws_region} \
  -e AWS_S3_BUCKET=${aws_s3_bucket.artifacts.id} \
  -e DATABASE_URL='postgresql://docagent_user:SuperSecretPass2026!@${aws_db_instance.postgres.endpoint}/docagent' \
  -e QDRANT_URL=http://127.0.0.1:6333 \
  -e QDRANT_COLLECTION_NAME=${var.collection_name} \
  -e NANOGPT_API_KEY=INSERT_YOUR_KEY_HERE \
  -e NANOGPT_BASE_URL=${var.nanogpt_base_url} \
  -e EMBED_BATCH_SIZE=2 \
  ${aws_ecr_repository.streamlit.repository_url}:latest \
  python pipelines/pipeline.py
EOT
  description = "Command to execute the ingestion pipeline inside the Backend EC2 host"
}