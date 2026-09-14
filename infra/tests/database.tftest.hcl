mock_provider "aws" {
  mock_data "aws_subnet" {
    defaults = {
      vpc_id                  = "vpc-0123456789abcdef0"
      availability_zone       = "us-east-1a"
      map_public_ip_on_launch = false
    }
  }
  mock_data "aws_route_table" {
    defaults = {
      vpc_id = "vpc-0123456789abcdef0"
      routes = [{
        cidr_block = "10.20.0.0/16"
        gateway_id = "local"
      }]
    }
  }
  mock_data "aws_security_group" {
    defaults = { vpc_id = "vpc-0123456789abcdef0" }
  }
  mock_resource "aws_security_group" {
    defaults = { id = "sg-0123456789abcdef3" }
  }
  mock_resource "aws_db_instance" {
    defaults = {
      address               = "oficina.example.us-east-1.rds.amazonaws.com"
      engine_version_actual = "16.10"
      master_user_secret = [{
        secret_arn    = "arn:aws:secretsmanager:us-east-1:123456789012:secret:rds-test"
        secret_status = "active"
        kms_key_id    = "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012"
      }]
    }
  }
}

override_data {
  target = data.aws_subnet.database["subnet-0123456789abcdef1"]
  values = {
    vpc_id                  = "vpc-0123456789abcdef0"
    availability_zone       = "us-east-1b"
    map_public_ip_on_launch = false
  }
}

variables {
  aws_account_id            = "123456789012"
  final_snapshot_identifier = "oficina-test-final"
  platform = {
    contract_version              = 1
    aws_region                    = "us-east-1"
    vpc_id                        = "vpc-0123456789abcdef0"
    database_subnet_ids           = ["subnet-0123456789abcdef0", "subnet-0123456789abcdef1"]
    application_security_group_id = "sg-0123456789abcdef0"
    lambda_security_group_ids = {
      staging  = "sg-0123456789abcdef1"
      producao = "sg-0123456789abcdef2"
    }
  }
}

# command=apply usa exclusivamente o provider mock, sem credenciais ou AWS real.
run "private_database_and_credentials" {
  command = apply
  assert {
    condition = (
      !aws_db_instance.database.publicly_accessible &&
      aws_db_instance.database.storage_encrypted &&
      aws_db_instance.database.manage_master_user_password &&
      aws_db_instance.database.password == null
    )
    error_message = "O banco deve ser privado e criptografado, com senha gerenciada pelo RDS."
  }
  assert {
    condition = (
      length(aws_vpc_security_group_ingress_rule.postgres) == 3 &&
      alltrue([for rule in aws_vpc_security_group_ingress_rule.postgres :
        rule.from_port == 5432 && rule.to_port == 5432 && rule.ip_protocol == "tcp" &&
        rule.cidr_ipv4 == null && rule.cidr_ipv6 == null &&
        contains(values(local.access_security_groups), rule.referenced_security_group_id)
      ]) &&
      length(aws_vpc_security_group_egress_rule.lambda_postgres) == 2 &&
      alltrue([for rule in aws_vpc_security_group_egress_rule.lambda_postgres :
        rule.from_port == 5432 && rule.to_port == 5432 &&
        rule.referenced_security_group_id == aws_security_group.database.id &&
        contains(values(var.platform.lambda_security_group_ids), rule.security_group_id)
      ])
    )
    error_message = "Somente os SGs da API e Lambdas devem acessar PostgreSQL."
  }
  assert {
    condition = (
      aws_db_instance.database.deletion_protection &&
      !aws_db_instance.database.skip_final_snapshot &&
      !aws_db_instance.database.delete_automated_backups &&
      aws_db_instance.database.backup_retention_period == 7 &&
      aws_db_instance.database.final_snapshot_identifier == "oficina-test-final"
    )
    error_message = "Backups e protecoes de exclusao devem estar ativos por padrao."
  }
  assert {
    condition = (
      anytrue([for p in aws_db_parameter_group.database.parameter : p.name == "rds.force_ssl" && p.value == "1"]) &&
      toset(aws_db_instance.database.enabled_cloudwatch_logs_exports) == toset(["postgresql", "upgrade"]) &&
      alltrue([for group in aws_cloudwatch_log_group.database : group.retention_in_days == 7])
    )
    error_message = "TLS e retencao dos logs devem estar configurados."
  }
  assert {
    condition = (
      output.database.contract_version == 1 &&
      output.database.ssl_mode == "VerifyFull" &&
      output.database.planned_environments.staging.database_name != output.database.planned_environments.producao.database_name &&
      output.database.planned_environments.staging.auth_role == "oficina_staging_auth" &&
      output.bootstrap_secret_arn == "arn:aws:secretsmanager:us-east-1:123456789012:secret:rds-test"
    )
    error_message = "Contrato deve separar ambientes e expor somente o ARN do segredo mestre."
  }
}

run "teardown_keeps_final_snapshot" {
  command = plan
  variables { allow_destroy = true }
  assert {
    condition = (
      !aws_db_instance.database.deletion_protection &&
      !aws_db_instance.database.skip_final_snapshot &&
      !aws_db_instance.database.delete_automated_backups
    )
    error_message = "Autorizar teardown nao pode eliminar o snapshot final nem backups retidos."
  }
}

run "reject_disabled_backups" {
  command = plan
  variables { backup_retention_days = 0 }
  expect_failures = [var.backup_retention_days]
}

run "reject_storage_ceiling" {
  command = plan
  variables { max_allocated_storage_gib = 20 }
  expect_failures = [var.max_allocated_storage_gib]
}

run "reject_region_mismatch" {
  command = plan
  variables { aws_region = "us-west-2" }
  expect_failures = [var.platform]
}

run "reject_invalid_snapshot" {
  command = plan
  variables { final_snapshot_identifier = "invalid--snapshot" }
  expect_failures = [var.final_snapshot_identifier]
}

run "reject_shared_logical_database" {
  command = plan
  variables {
    environments = {
      staging  = { branch = "develop", database_name = "oficina" }
      producao = { branch = "master", database_name = "oficina" }
    }
  }
  expect_failures = [var.environments]
}

run "reject_single_availability_zone" {
  command = plan
  override_data {
    target = data.aws_subnet.database["subnet-0123456789abcdef1"]
    values = {
      vpc_id                  = "vpc-0123456789abcdef0"
      availability_zone       = "us-east-1a"
      map_public_ip_on_launch = false
    }
  }
  expect_failures = [aws_db_subnet_group.database]
}

run "reject_internet_route" {
  command = plan
  override_data {
    target = data.aws_route_table.database["subnet-0123456789abcdef0"]
    values = {
      vpc_id = "vpc-0123456789abcdef0"
      routes = [{
        cidr_block = "0.0.0.0/0"
        gateway_id = "igw-0123456789abcdef0"
      }]
    }
  }
  expect_failures = [aws_db_subnet_group.database]
}

run "reject_security_group_in_other_vpc" {
  command = plan
  override_data {
    target = data.aws_security_group.clients["application"]
    values = { vpc_id = "vpc-0123456789abcdef9" }
  }
  expect_failures = [aws_security_group.database]
}

run "reject_subnet_in_other_vpc" {
  command = plan
  override_data {
    target = data.aws_subnet.database["subnet-0123456789abcdef1"]
    values = {
      vpc_id                  = "vpc-0123456789abcdef9"
      availability_zone       = "us-east-1b"
      map_public_ip_on_launch = false
    }
  }
  expect_failures = [aws_db_subnet_group.database]
}
