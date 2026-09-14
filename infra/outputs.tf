output "database" {
  description = "Contrato de conectividade; bancos logicos e roles ainda exigem bootstrap."
  value = {
    contract_version      = 1
    aws_region            = var.aws_region
    vpc_id                = var.platform.vpc_id
    identifier            = aws_db_instance.database.identifier
    address               = aws_db_instance.database.address
    port                  = aws_db_instance.database.port
    engine_version_actual = aws_db_instance.database.engine_version_actual
    security_group_id     = aws_security_group.database.id
    ssl_mode              = "VerifyFull"
    planned_environments  = local.planned_environments
  }
}

output "bootstrap_secret_arn" {
  description = "ARN do segredo mestre gerenciado pelo RDS. Apenas bootstrap; nunca configurar como credencial da API/Lambda."
  value       = aws_db_instance.database.master_user_secret[0].secret_arn
}
