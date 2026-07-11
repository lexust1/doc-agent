# Makefile – Doc Agent deployment helper
# =============================================================================
# This Makefile automates the deployment process by executing targets in a safe,
# sequential order to prevent cloud resource dependency conflicts.
# =============================================================================

AWS_REGION ?= us-east-1
ECR_REPO   ?= doc-agent-streamlit
IMAGE      ?= doc-agent-streamlit:latest
DOCKERFILE ?= docker/Dockerfile.streamlit

# Build the Streamlit image locally from the project Dockerfile.
# The build context is set to the current directory (.).
# CRITICAL FIX: Force the build platform to linux/amd64. 
# This ensures that images built on Apple Silicon (M1/M2/M3) or other ARM processors
# will run successfully on standard AWS EC2 instances (like t3.medium) which are x86_64.
build:
	docker build --platform linux/amd64 -t $(IMAGE) -f $(DOCKERFILE) .

# Authenticate the local Docker client against the remote Amazon ECR registry.
# This token is required before pushing any container images to AWS.
ecr-login:
	aws ecr get-login-password --region $(AWS_REGION) | \
		docker login --username AWS --password-stdin $$(aws sts get-caller-identity --query Account --output text).dkr.ecr.$(AWS_REGION).amazonaws.com

# Provision ONLY the ECR repository using Terraform targeting.
# This guarantees the registry exists before an image push is attempted.
ecr-infra: terraform-init
	terraform -chdir=terraform apply -target=aws_ecr_repository.streamlit -auto-approve

# Tag the local Docker image and push it to the newly created ECR repository.
# It automatically triggers 'ecr-infra' and 'ecr-login' targets first.
ecr-push: ecr-infra ecr-login
	@ECR_URL=$$(terraform -chdir=terraform output -raw ecr_repository_url 2>/dev/null || echo ""); \
	if [ -z "$$ECR_URL" ]; then \
		echo "Error: ECR repository not found. Run 'make ecr-infra' first."; \
		exit 1; \
	fi; \
	docker tag $(IMAGE) $$ECR_URL:latest && \
	docker push $$ECR_URL:latest

# Initialize the Terraform workspace and download required AWS plugins.
terraform-init:
	terraform -chdir=terraform init

# Generate a speculative execution plan to review infrastructure changes.
terraform-plan: terraform-init
	terraform -chdir=terraform plan

# Deploy the full infrastructure stack, including the EC2 instance.
# Since the image is already pushed, the instance pulls it instantly on boot.
terraform-apply: terraform-init
	terraform -chdir=terraform apply -auto-approve

# Execute the entire end-to-end deployment pipeline in a safe sequence.
# Execution order: Build Image -> Create ECR -> Push Image -> Create EC2 Host
deploy: build ecr-push terraform-apply
	@echo "========================================================================="
	@echo "✅ Infrastructure deployment complete!"
	@echo "🌐 Streamlit UI URL (accessible in a minute):"
	@terraform -chdir=terraform output -raw streamlit_url
	@echo "\n🚀 Copy the command below and execute it inside the Backend EC2 host:"
	@terraform -chdir=terraform output -raw pipeline_run_command
	@echo "========================================================================="

.PHONY: build ecr-login ecr-infra ecr-push terraform-init terraform-plan terraform-apply deploy