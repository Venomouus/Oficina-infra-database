output "planned_database" {
  description = "Configuracoes planejadas; nao representam uma instancia RDS existente."
  value       = local.planned_database
}

output "planned_environments" {
  description = "Nomes planejados de bancos e roles; nao sao usuarios criados nem credenciais."
  value       = local.planned_environments
}
