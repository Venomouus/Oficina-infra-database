# Planejamento inicial. Ainda nao ha provider AWS, banco, usuarios ou backups reais.
locals {
  planned_database = {
    identifier             = "${var.project_name}-lab-postgres"
    region                 = var.aws_region
    engine                 = "postgres"
    major_version          = var.postgres_major_version
    allocated_storage_gib  = var.allocated_storage_gib
    backup_retention_days  = var.backup_retention_days
    multi_az               = var.multi_az
    publicly_accessible    = false
    storage_encrypted      = true
    deletion_protection    = true
    require_final_snapshot = true
  }

  planned_environments = {
    for name, environment in var.environments : name => {
      branch          = environment.branch
      database_name   = environment.database_name
      app_role        = "${environment.database_name}_app"
      auth_role       = "${environment.database_name}_auth"
      migrations_role = "${environment.database_name}_migrations"
    }
  }
}
