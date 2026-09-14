# Apenas containers de segredos. Valores sao gravados fora do Terraform no bootstrap.
# O segredo auth/database pertence ao repositorio Oficina-serverless.
locals {
  runtime_credentials = merge([
    for environment, config in local.planned_environments : {
      for purpose in ["app", "migrations"] : "${environment}_${purpose}" => {
        environment = environment
        purpose     = purpose
        username    = config["${purpose}_role"]
      }
    }
  ]...)
}
resource "aws_secretsmanager_secret" "runtime" {
  for_each                = local.runtime_credentials
  name                    = "${var.project_name}/${each.value.environment}/database/${each.value.purpose}"
  description             = "Credencial PostgreSQL ${each.value.username}; valor provisionado pelo bootstrap privado"
  recovery_window_in_days = 30
  tags = {
    Environment = each.value.environment
    Purpose     = each.value.purpose
  }
}
output "runtime_secret_arns" {
  description = "Destinos das credenciais app/migrations. JSON de cada valor: username e password. Sem leitura de valores pelo Terraform."
  value = {
    for environment in keys(var.environments) : environment => {
      for purpose in ["app", "migrations"] : purpose => aws_secretsmanager_secret.runtime["${environment}_${purpose}"].arn
    }
  }
}
