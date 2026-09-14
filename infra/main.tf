locals {
  identifier = "${var.project_name}-lab-postgres"
  access_security_groups = merge(
    { application = var.platform.application_security_group_id },
    { for name, id in var.platform.lambda_security_group_ids : "lambda_${name}" => id }
  )
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

data "aws_subnet" "database" {
  for_each = toset(var.platform.database_subnet_ids)
  id       = each.value
}

data "aws_route_table" "database" {
  for_each  = toset(var.platform.database_subnet_ids)
  subnet_id = each.value
}

data "aws_security_group" "clients" {
  for_each = local.access_security_groups
  id       = each.value
}

resource "aws_db_subnet_group" "database" {
  name       = local.identifier
  subnet_ids = var.platform.database_subnet_ids
  lifecycle {
    precondition {
      condition = alltrue([
        for subnet in data.aws_subnet.database :
        subnet.vpc_id == var.platform.vpc_id && !subnet.map_public_ip_on_launch
      ])
      error_message = "As sub-redes devem pertencer a VPC da plataforma e nao atribuir IP publico."
    }
    precondition {
      condition     = length(toset([for subnet in data.aws_subnet.database : subnet.availability_zone])) >= 2
      error_message = "O RDS exige sub-redes em pelo menos duas zonas de disponibilidade."
    }
    precondition {
      condition = alltrue([
        for table in data.aws_route_table.database :
        table.vpc_id == var.platform.vpc_id && length(table.routes) > 0 &&
        alltrue([for route in table.routes : route.gateway_id == "local"])
      ])
      error_message = "Use sub-redes isoladas: as tabelas devem conter somente rotas locais da VPC."
    }
  }
}

resource "aws_security_group" "database" {
  name_prefix = "${local.identifier}-"
  description = "PostgreSQL privado para API e autenticacao."
  vpc_id      = var.platform.vpc_id
  lifecycle {
    create_before_destroy = true
    precondition {
      condition     = alltrue([for group in data.aws_security_group.clients : group.vpc_id == var.platform.vpc_id])
      error_message = "Todos os security groups clientes devem pertencer a VPC da plataforma."
    }
  }
}

resource "aws_vpc_security_group_ingress_rule" "postgres" {
  for_each                     = local.access_security_groups
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "PostgreSQL: ${each.key}"
}

# Este repositorio e dono apenas destas regras adicionais dos SGs Lambda.
resource "aws_vpc_security_group_egress_rule" "lambda_postgres" {
  for_each                     = var.platform.lambda_security_group_ids
  security_group_id            = each.value
  referenced_security_group_id = aws_security_group.database.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "PostgreSQL privado: ${each.key}"
}

resource "aws_db_parameter_group" "database" {
  name_prefix = "${local.identifier}-"
  family      = "postgres${var.postgres_major_version}"
  description = "Exige TLS no PostgreSQL da oficina."
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_cloudwatch_log_group" "database" {
  for_each          = toset(["postgresql", "upgrade"])
  name              = "/aws/rds/instance/${local.identifier}/${each.value}"
  retention_in_days = 7
}

resource "aws_db_instance" "database" {
  identifier                      = local.identifier
  engine                          = "postgres"
  engine_version                  = var.postgres_major_version
  engine_lifecycle_support        = "open-source-rds-extended-support-disabled"
  instance_class                  = var.instance_class
  port                            = 5432
  username                        = "oficina_admin"
  manage_master_user_password     = true
  db_subnet_group_name            = aws_db_subnet_group.database.name
  vpc_security_group_ids          = [aws_security_group.database.id]
  parameter_group_name            = aws_db_parameter_group.database.name
  publicly_accessible             = false
  multi_az                        = var.multi_az
  storage_type                    = "gp3"
  allocated_storage               = var.allocated_storage_gib
  max_allocated_storage           = var.max_allocated_storage_gib
  storage_encrypted               = true
  backup_retention_period         = var.backup_retention_days
  backup_window                   = "03:00-04:00"
  maintenance_window              = "sun:05:00-sun:06:00"
  copy_tags_to_snapshot           = true
  delete_automated_backups        = false
  deletion_protection             = !var.allow_destroy
  skip_final_snapshot             = false
  final_snapshot_identifier       = var.final_snapshot_identifier
  apply_immediately               = false
  auto_minor_version_upgrade      = true
  allow_major_version_upgrade     = false
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
  depends_on                      = [aws_cloudwatch_log_group.database]
}
