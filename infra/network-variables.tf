variable "aws_account_id" {
  description = "Conta autorizada a receber os recursos."
  type        = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "Informe o ID AWS de 12 digitos."
  }
}

variable "platform" {
  description = "Campos do output platform do infra-kubernetes, apos provisionar a rede na mesma conta."
  type = object({
    contract_version              = number
    aws_region                    = string
    vpc_id                        = string
    database_subnet_ids           = list(string)
    application_security_group_id = string
    lambda_security_group_ids     = map(string)
  })
  validation {
    condition     = var.platform.contract_version == 1 && var.platform.aws_region == var.aws_region
    error_message = "Use o contrato platform versao 1 na mesma regiao do banco."
  }
  validation {
    condition = (
      can(regex("^vpc-[0-9a-f]{8}([0-9a-f]{9})?$", var.platform.vpc_id)) &&
      length(toset(var.platform.database_subnet_ids)) >= 2 &&
      length(toset(var.platform.database_subnet_ids)) == length(var.platform.database_subnet_ids) &&
      alltrue([for id in var.platform.database_subnet_ids : can(regex("^subnet-[0-9a-f]{8}([0-9a-f]{9})?$", id))])
    )
    error_message = "Informe uma VPC e pelo menos duas sub-redes distintas com IDs AWS validos."
  }
  validation {
    condition = (
      toset(keys(var.platform.lambda_security_group_ids)) == toset(["staging", "producao"]) &&
      length(toset(concat([var.platform.application_security_group_id], values(var.platform.lambda_security_group_ids)))) == 3 &&
      alltrue([for id in concat([var.platform.application_security_group_id], values(var.platform.lambda_security_group_ids)) :
        can(regex("^sg-[0-9a-f]{8}([0-9a-f]{9})?$", id))
      ])
    )
    error_message = "Use tres SGs distintos: aplicacao e Lambdas staging/producao."
  }
}

variable "instance_class" {
  description = "Classe ARM do laboratorio. Verificar disponibilidade regional antes do plano real."
  type        = string
  default     = "db.t4g.small"
  validation {
    condition     = contains(["db.t4g.micro", "db.t4g.small", "db.t4g.medium"], var.instance_class)
    error_message = "Classes previstas para este laboratorio: db.t4g.micro, db.t4g.small ou db.t4g.medium."
  }
}

variable "max_allocated_storage_gib" {
  description = "Teto do autoscaling de armazenamento; crescimento nao e revertido automaticamente."
  type        = number
  default     = 100
  validation {
    condition = (
      var.max_allocated_storage_gib >= ceil(var.allocated_storage_gib * 1.1) &&
      var.max_allocated_storage_gib <= 200 &&
      floor(var.max_allocated_storage_gib) == var.max_allocated_storage_gib
    )
    error_message = "Use um inteiro ate 200 GiB, pelo menos 10% acima do armazenamento inicial."
  }
}

variable "allow_destroy" {
  description = "Excecao para teardown: exige apply previo e snapshot final obrigatorio."
  type        = bool
  default     = false
}

variable "final_snapshot_identifier" {
  description = "Nome unico do snapshot final, necessario para excluir o RDS."
  type        = string
  validation {
    condition = (
      can(regex("^[a-zA-Z][a-zA-Z0-9-]{0,254}$", var.final_snapshot_identifier)) &&
      !endswith(var.final_snapshot_identifier, "-") &&
      !strcontains(var.final_snapshot_identifier, "--")
    )
    error_message = "Use 1 a 255 caracteres alfanumericos/hifens, iniciando com letra, sem hifens duplos ou finais."
  }
}
