# Operacao do Terraform RDS

## Entradas e contrato de rede

Copie `terraform.tfvars.example` para `terraform.tfvars` e substitua a conta e os IDs. O objeto `platform` utiliza os campos do output de mesmo nome do infra-kubernetes:

- `contract_version = 1`, `aws_region` e `vpc_id`.
- `database_subnet_ids`: sub-redes isoladas em pelo menos duas AZs.
- `application_security_group_id`: SG do cluster compartilhado com os nodes/pods.
- `lambda_security_group_ids`: SGs de staging e producao.

Os data sources consultam as sub-redes, tabelas de rotas efetivas e SGs. O plano rejeita outra VPC, uma unica AZ, atribuicao automatica de IP publico, rotas externas ou regioes divergentes. O provider restringe a conta com `allowed_account_ids`.

O infra-kubernetes continua dono dos SGs Lambda e de suas regras HTTPS. Este repositorio possui somente suas duas regras adicionais de saida PostgreSQL para o SG do banco. Evite adicionar as mesmas regras inline no outro state.

## Backend e plano autenticado — etapa posterior

Requer VPC provisionada, credenciais temporarias autorizadas, bucket de state existente com criptografia/versionamento, bloqueio de acesso publico e IAM limitado ao prefixo do banco. As permissoes do lockfile S3 devem permitir criar, ler e remover o arquivo de lock.

1. Copie `backend.hcl.example` para `backend.hcl` e informe o bucket real.
2. Mantenha a chave exclusiva `oficina/shared/database.tfstate`. Nao reutilize a chave do Kubernetes, nem crie states separados para develop/master dessa mesma instancia.
3. Preencha `terraform.tfvars`, incluindo um nome de snapshot final unico.
4. Confirme a conta e a regiao autenticadas, a disponibilidade da classe/versao e os custos esperados.
5. Inicialize o backend e produza o plano para revisao:

```powershell
terraform -chdir=infra init -reconfigure -backend-config=backend.hcl -input=false
terraform -chdir=infra plan -out=database.tfplan
terraform -chdir=infra show -no-color database.tfplan
```

Esses passos ainda nao criam o RDS. A aplicacao do plano revisado pertence a etapa de provisionamento. Nao execute um apply apenas porque o PR foi integrado. O plano salvo e o state devem ser tratados como arquivos restritos e nao versionados.

Os testes mock nao demonstram permissoes IAM, quotas, capacidade regional, conectividade real ou sucesso do deploy. A selecao `engine_version = "16"` permite ao RDS resolver uma minor suportada, com atualizacoes menores habilitadas; `engine_version_actual` informa a versao resultante.

## Credenciais, TLS e bootstrap

RDS cria e gerencia a senha de `oficina_admin` no Secrets Manager. O output `bootstrap_secret_arn` identifica esse segredo sem ler seu valor. Nao usar a conta mestre no runtime, em manifests ou em variaveis publicas de pipeline.

O output `database` fornece endereco, porta, SG e `planned_environments`. Os nomes planejados **nao significam que os bancos/usuarios ja existem**. O bootstrap deve rodar por uma conexao privada autorizada, por exemplo um Job controlado no EKS:

1. Obter a credencial mestre com IAM restrito e sem imprimir o segredo.
2. Criar bancos distintos e roles de migrations/app/auth para cada ambiente.
3. Revogar `CONNECT` de PUBLIC em cada banco e conceder acesso somente as roles daquele ambiente.
4. Revogar privilegios excessivos no schema public. A role app deve ter somente o DML necessario; auth deve consultar somente as colunas de cliente exigidas pelo autenticador; migrations deve possuir as permissoes de DDL.
5. Configurar default privileges para os objetos futuros do proprietario usado nas migrations.
6. Guardar as credenciais das roles em segredos separados, com IAM limitado por workload/ambiente e uma estrategia de rotacao.
7. Executar migrations como tarefa separada e validar os grants usando as roles reais.

A API atual chama migrations no startup. Essa dependencia deve ser removida/condicionada antes de instalar uma credencial de runtime sem DDL. Nao contornar isso usando o usuario mestre na API.

Configure Npgsql com o hostname RDS do output, `SSL Mode=VerifyFull` e a cadeia de CA RDS apropriada no trust store ou em `Root Certificate`. Nao use IP nem `Trust Server Certificate=true`. O parameter group exige TLS, mas a verificacao da identidade do servidor depende tambem do cliente. Planeje atualizacao da CA.

Referencias: [senha gerenciada pelo RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-secrets-manager.html), [TLS no PostgreSQL RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html).

## Backups, alteracoes e teardown

Backups automaticos: sete dias por padrao, janela 03:00–04:00 UTC. Manutencao: domingo 05:00–06:00 UTC. Alteracoes nao sao aplicadas imediatamente; revise o impacto de reboot dos parametros. PostgreSQL e upgrade exportam logs com retencao de sete dias.

Para a demonstracao, restaure um backup/snapshot em uma instancia separada e confira dados e integridade. Backups configurados nao comprovam recuperacao. Nao troque o endpoint da aplicacao antes de validar a restauracao.

A exclusao exige duas etapas deliberadas: primeiro configurar `allow_destroy=true`, revisar e aplicar essa mudanca; depois revisar o plano de destruicao. `skip_final_snapshot` permanece false e o nome de snapshot deve ser unico. Backups automaticos sao retidos conforme a politica RDS. Nao remover a protecao apenas para vencer um erro de apply.

Destruir o banco e suas regras adicionais antes da rede/SGs do infra-kubernetes. Snapshots, backups e o segredo gerenciado possuem ciclos de vida proprios: confira os recursos remanescentes e as cobrancas apos o teardown. Nunca apague o state como forma de excluir recursos.

A instancia default `db.t4g.small`, storage, Secrets Manager e logs geram custos quando provisionados. Single-AZ reduz disponibilidade; `multi_az=true` muda o custo. Autoscaling pode aumentar o armazenamento ate o teto e nao o reduz automaticamente.
