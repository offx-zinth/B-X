output "database_host" {
  description = "RDS endpoint for DATABASE_URL (Helm env.databaseUrl)"
  value       = aws_db_instance.xray.address
}

output "redis_endpoint" {
  description = "ElastiCache primary endpoint for REDIS_URL (Helm env.redisUrl)"
  value       = aws_elasticache_replication_group.xray.primary_endpoint_address
}
