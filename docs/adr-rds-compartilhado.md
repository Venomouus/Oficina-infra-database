# ADR — RDS PostgreSQL compartilhado no laboratorio

Status: aceito para a fundacao do laboratorio; provisionamento e bootstrap pendentes.

## Contexto e decisao

A API ja usa PostgreSQL e EF Core, com relacionamentos, transacoes, valores monetarios e migrations. Usar RDS PostgreSQL 16 preserva esse modelo e transfere ao servico gerenciado a operacao de backups e manutencao da instancia.

Uma unica instancia privada atende dois bancos logicos, cada um com roles e segredos proprios. O default e Single-AZ, db.t4g.small e gp3 de 20 GiB com crescimento limitado a 100 GiB. A opcao Multi-AZ permanece configuravel.

## Alternativas

- PostgreSQL dentro do Kubernetes exigiria operar volumes, backups, restauracao e disponibilidade do banco junto com o cluster.
- Uma instancia RDS por ambiente melhoraria isolamento de falhas/capacidade, com mais recursos e custos de laboratorio.
- Um banco NoSQL exigiria remodelar relacionamentos e transacoes da aplicacao existente, sem beneficio demonstrado para esta etapa.

## Consequencias

Compartilhar a instancia reduz a quantidade de recursos, mas compartilha capacidade, manutencao e dominio de falha. Single-AZ nao tem failover Multi-AZ. Segregacao SQL e credenciais sao obrigatorias; SGs permitem conectividade, nao isolamento entre bancos.

Backups, snapshot final e protecao de exclusao ficam ativos por padrao. O teardown precisa ser planejado e custos de snapshots/logs/segredos devem ser verificados. Nenhum teste mock substitui ensaio de restauracao ou validacao de conectividade na AWS.

A senha mestre e gerenciada pelo RDS. O Terraform expoe apenas seu ARN; usuarios de runtime e sua rotacao serao responsabilidade do bootstrap e da integracao dos workloads.

Referencias: [recurso aws_db_instance](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/db_instance), [RDS com Secrets Manager](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-secrets-manager.html), [TLS PostgreSQL](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html).
