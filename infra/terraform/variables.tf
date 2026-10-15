variable "name" {
  description = "Resource name prefix"
  type        = string
  default     = "xray"
}

variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "subnet_ids" {
  description = "Private subnet IDs for RDS"
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security group IDs for RDS/ElastiCache"
  type        = list(string)
}

variable "cache_subnet_group" {
  description = "ElastiCache subnet group name"
  type        = string
}

variable "db_instance_class" {
  type    = string
  default = "db.r6g.large"
}

variable "db_parameter_group" {
  description = "Parameter group with pgvector-friendly settings"
  type        = string
  default     = "default.postgres16"
}

variable "redis_node_type" {
  type    = string
  default = "cache.r6g.large"
}
