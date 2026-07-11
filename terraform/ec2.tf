# ec2.tf

# Retrieve the latest Amazon Linux 2 AMI for the current region.
data "aws_ami" "amazon_linux_2" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["amzn2-ami-hvm-*-x86_64-gp2"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Dynamically fetch official AWS IP ranges for the EC2 Instance Connect service
# in your specific region to allow secure web-console access.
data "aws_ip_ranges" "ec2_instance_connect" {
  regions  = [var.aws_region]
  services = ["ec2_instance_connect"]
}

# =============================================================================
# SHARED IAM CONFIGURATION
# =============================================================================

# Create an IAM role granting the EC2 service permission to assume it.
resource "aws_iam_role" "ec2_role" {
  name = "doc-agent-ec2-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

# Attach the AWS-managed ReadOnly ECR policy so the instances can pull Docker images.
resource "aws_iam_role_policy_attachment" "ecr_pull" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# Attach an inline IAM policy granting the EC2 instances permission to manage objects inside the S3 bucket
resource "aws_iam_role_policy" "ec2_s3_access" {
  name = "doc-agent-ec2-s3-access"
  role = aws_iam_role.ec2_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.artifacts.arn,
          "${aws_s3_bucket.artifacts.arn}/*"
        ]
      }
    ]
  })
}

# Create an instance profile to attach the IAM role to the EC2 instances.
resource "aws_iam_instance_profile" "ec2_profile" {
  name = "doc-agent-ec2-profile"
  role = aws_iam_role.ec2_role.name
}

# =============================================================================
# BACKEND INSTANCE (WORKER + QDRANT)
# =============================================================================

# Define a security group for the backend node.
resource "aws_security_group" "backend_sg" {
  name_prefix = "doc-agent-backend-sg-"
  description = "Allow inbound Qdrant traffic from Frontend, and SSH from user"

  # Allow inbound TCP traffic on port 6333 (Qdrant API) strictly from the Frontend SG
  ingress {
    description     = "Qdrant API access from Frontend only"
    from_port       = 6333
    to_port         = 6333
    protocol        = "tcp"
    security_groups = [aws_security_group.frontend_sg.id]
  }

  # Allow inbound SSH (port 22) ONLY from your personal IP and the official
  # AWS EC2 Instance Connect service CIDR blocks.
  ingress {
    description = "SSH access for user IP and AWS EC2 Instance Connect"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = concat([var.allowed_cidr], data.aws_ip_ranges.ec2_instance_connect.cidr_blocks)
  }

  # Allow all outbound traffic to the internet
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Provision the Backend EC2 instance to host Qdrant and offline processing.
resource "aws_instance" "backend" {
  ami                         = data.aws_ami.amazon_linux_2.id
  instance_type               = "t3.medium"
  associate_public_ip_address = true

  root_block_device {
    volume_size = 30
    volume_type = "gp2"
  }
  
  # Attach the SSH key pair only if a name is provided in the variables
  key_name                    = var.key_name != "" ? var.key_name : null
  
  vpc_security_group_ids      = [aws_security_group.backend_sg.id]
  iam_instance_profile        = aws_iam_instance_profile.ec2_profile.name

  # Boot script to install Docker and start Qdrant
  user_data = <<-EOF
    #!/bin/bash
    # 1. Update OS packages and install Docker
    yum update -y
    amazon-linux-extras install docker -y
    service docker start
    usermod -a -G docker ec2-user

    # 2. Start Qdrant Vector Database
    mkdir -p /home/ec2-user/qdrant_storage
    docker run -d --restart unless-stopped --name qdrant \
      -p 6333:6333 -p 6334:6334 \
      -v /home/ec2-user/qdrant_storage:/qdrant/storage \
      qdrant/qdrant:latest
  EOF

  tags = {
    Name = "doc-agent-backend"
  }
}

# =============================================================================
# FRONTEND INSTANCE (STREAMLIT UI)
# =============================================================================

# Define a security group for the frontend node.
resource "aws_security_group" "frontend_sg" {
  name_prefix = "doc-agent-frontend-sg-"
  description = "Allow inbound Streamlit traffic from user, and SSH"

  # Allow inbound TCP traffic on port 8501 (Streamlit UI) from your IP only
  ingress {
    description = "Streamlit web UI"
    from_port   = 8501
    to_port     = 8501
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  # Allow inbound SSH (port 22)
  ingress {
    description = "SSH access for user IP and AWS EC2 Instance Connect"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = concat([var.allowed_cidr], data.aws_ip_ranges.ec2_instance_connect.cidr_blocks)
  }

  # Allow all outbound traffic to the internet (required for pulling packages/images)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Provision the Frontend EC2 instance to host the Streamlit application.
resource "aws_instance" "frontend" {
  ami                         = data.aws_ami.amazon_linux_2.id
  instance_type               = "t3.medium"
  associate_public_ip_address = true

  root_block_device {
    volume_size = 30
    volume_type = "gp2"
  }
  
  # Attach the SSH key pair only if a name is provided in the variables
  key_name                    = var.key_name != "" ? var.key_name : null
  
  vpc_security_group_ids      = [aws_security_group.frontend_sg.id]
  iam_instance_profile        = aws_iam_instance_profile.ec2_profile.name

  # Ensure the backend is created first so we can inject its private IP
  depends_on = [aws_instance.backend]

  # Boot script to install Docker, log into ECR, and run Streamlit
  user_data = <<-EOF
    #!/bin/bash
    # 1. Update OS packages and install Docker
    yum update -y
    amazon-linux-extras install docker -y
    service docker start
    usermod -a -G docker ec2-user

    # 2. Authenticate Docker client to the AWS ECR registry
    aws ecr get-login-password --region ${var.aws_region} | \
      docker login --username AWS --password-stdin ${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com

    # 3. Pull the Streamlit application image
    IMAGE="${aws_ecr_repository.streamlit.repository_url}:latest"
    docker pull "$IMAGE"

    # 4. Run the Streamlit container.
    # Dynamically inject the Backend's private IP for Qdrant access.
    docker run -d --restart unless-stopped --name streamlit -p 8501:8501 \
      -e QDRANT_URL=http://${aws_instance.backend.private_ip}:6333 \
      -e QDRANT_COLLECTION_NAME=${var.collection_name} \
      -e DEPLOYMENT_MODE=aws \
      -e NANOGPT_API_KEY=${var.nanogpt_api_key} \
      -e NANOGPT_BASE_URL=${var.nanogpt_base_url} \
      -e ARTIFACTS_BUCKET=${aws_s3_bucket.artifacts.id} \
      "$IMAGE" streamlit run ui/app.py --server.address=0.0.0.0
  EOF

  tags = {
    Name = "doc-agent-frontend"
  }
}

# Output the final public URL to easily access the Streamlit app in the browser
output "streamlit_url" {
  value = "http://${aws_instance.frontend.public_ip}:8501"
}

# Output the instance IDs for reference
output "backend_instance_id" {
  value = aws_instance.backend.id
}

output "frontend_instance_id" {
  value = aws_instance.frontend.id
}