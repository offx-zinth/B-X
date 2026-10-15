# Managed data layer for Business X-Ray (RDS Postgres + ElastiCache Redis).
# Usage: terraform -chdir=infra/terraform init && terraform apply.
# The Helm chart then points at these endpoints with postgresql.enabled=false
# and redis.enabled=false.
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.0" }
  }
}

provider "aws" {
  region = var.region
}

resource "aws_db_subnet_group" "xray" {
  name       = "${var.name}-db-subnets"
  subnet_ids = var.subnet_ids
}

resource "aws_db_instance" "xray" {
  identifier             = "${var.name}-pg"
  engine                 = "postgres"
  engine_version         = "16"
  instance_class         = var.db_instance_class
  allocated_storage      = 100
  storage_encrypted      = true
  db_name                = "xray"
  username               = "xray"
  manage_master_user_password = true
  db_subnet_group_name   = aws_db_subnet_group.xray.name
  vpc_security_group_ids = var.security_group_ids
  backup_retention_period = 7
  deletion_protection    = true
  # pgvector: enable the extension on RDS, then init.sql / Alembic 0002
  # creates node_embeddings on first migrate.
  parameter_group_name = var.db_parameter_group
}

resource "aws_elasticache_replication_group" "xray" {
  replication_group_id = "${var.name}-redis"
  description          = "Business X-Ray job broker"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.redis_node_type
  num_cache_clusters   = 2
  automatic_failover_enabled = true
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  subnet_group_name    = var.cache_subnet_group
  security_group_ids   = var.security_group_ids
}
