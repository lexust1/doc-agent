# rds.tf

# Create a dedicated Security Group for the RDS database
resource "aws_security_group" "rds_sg" {
  name_prefix = "doc-agent-rds-sg-"
  description = "Allow PostgreSQL traffic strictly from the Backend EC2 instance"

  ingress {
    description     = "PostgreSQL access from Backend"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    # IMPORTANT: We link this to the Backend's security group.
    # Only the worker node can talk to this database.
    security_groups = [aws_security_group.backend_sg.id] 
  }
}

# Provision a managed PostgreSQL instance
resource "aws_db_instance" "postgres" {
  identifier             = "doc-agent-db"
  engine                 = "postgres"
  engine_version         = "16"               # Adjust if your region requires an older version like 15.x
  instance_class         = "db.t3.micro"        # Cheapest instance suitable for a sandbox
  allocated_storage      = 20
  
  db_name                = "docagent"
  username               = "docagent_user"
  password               = "SuperSecretPass2026!" # Hardcoded for sandbox convenience
  
  vpc_security_group_ids = [aws_security_group.rds_sg.id]
  
  # CRITICAL FOR SANDBOX: Do not create a backup snapshot when destroying
  skip_final_snapshot    = true
  publicly_accessible    = false
}

# Output the connection endpoint so Terraform can pass it to Docker
output "rds_endpoint" {
  value = aws_db_instance.postgres.endpoint
}