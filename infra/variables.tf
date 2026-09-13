variable "project_name" {
  description = "Prefixo do banco gerenciado compartilhado de laboratorio."
  type        = string
  default     = "oficina"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,29}$", var.project_name))
    error_message = "Use de 2 a 30 caracteres: letras minusculas, numeros e hifens, iniciando com letra."
  }
}

variable "aws_region" {
  description = "Regiao planejada; deve ser alinhada com a rede do repositorio Kubernetes."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]+$", var.aws_region))
    error_message = "Informe uma regiao AWS no formato us-east-1."
  }
}

variable "postgres_major_version" {
  description = "Versao principal planejada, alinhada ao PostgreSQL 16 local. A versao RDS exata sera verificada antes do deploy."
  type        = string
  default     = "16"

  validation {
    condition     = can(regex("^[1-9][0-9]+$", var.postgres_major_version))
    error_message = "Informe a versao principal numerica, como 16."
  }
}

variable "allocated_storage_gib" {
  description = "Armazenamento planejado. Limite de projeto para o laboratorio: 20 a 100 GiB."
  type        = number
  default     = 20

  validation {
    condition = (
      var.allocated_storage_gib >= 20 &&
      var.allocated_storage_gib <= 100 &&
      floor(var.allocated_storage_gib) == var.allocated_storage_gib
    )
    error_message = "Use um numero inteiro entre 20 e 100 GiB para o laboratorio."
  }
}

variable "backup_retention_days" {
  description = "Retencao planejada para backups automaticos, sem desabilita-los."
  type        = number
  default     = 7

  validation {
    condition = (
      var.backup_retention_days >= 1 &&
      var.backup_retention_days <= 35 &&
      floor(var.backup_retention_days) == var.backup_retention_days
    )
    error_message = "Use um numero inteiro entre 1 e 35 dias."
  }
}

variable "multi_az" {
  description = "Configuracao futura de disponibilidade. false e uma concessao de custo do laboratorio, sem failover Multi-AZ."
  type        = bool
  default     = false
}

variable "environments" {
  description = "Bancos logicos distintos na mesma instancia RDS planejada."
  type = map(object({
    branch        = string
    database_name = string
  }))
  default = {
    staging = {
      branch        = "develop"
      database_name = "oficina_staging"
    }
    producao = {
      branch        = "master"
      database_name = "oficina_producao"
    }
  }

  validation {
    condition = (
      toset(keys(var.environments)) == toset(["staging", "producao"]) &&
      try(var.environments["staging"].branch == "develop", false) &&
      try(var.environments["producao"].branch == "master", false) &&
      length(distinct([for environment in values(var.environments) : environment.database_name])) == 2 &&
      alltrue([
        for environment in values(var.environments) :
        can(regex("^[a-z][a-z0-9_]{1,31}$", environment.database_name))
      ])
    )
    error_message = "Configure staging/develop e producao/master com nomes de banco distintos, de 2 a 32 caracteres minusculos, numeros ou underscore, iniciando com letra."
  }
}
