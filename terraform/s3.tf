# s3.tf

# Create a secure private S3 bucket for document artifacts and intermediate processing stages
resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "doc-agent-artifacts-"
  
  # force_destroy allows the bucket to be deleted even if it contains files.
  # This is perfect for sandbox environments to prevent stuck terraform destroy commands.
  force_destroy = true

  tags = {
    Name = "doc-agent-artifacts"
  }
}

# Explicitly block all public access to ensure data security
resource "aws_s3_bucket_public_access_block" "artifacts_privacy" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Output the generated bucket name so we can pass it to the application container
output "s3_bucket_name" {
  value = aws_s3_bucket.artifacts.id
}