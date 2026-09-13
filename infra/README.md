# Base Terraform do banco

Esta pasta define variaveis validadas e configuracoes planejadas. Ainda nao
possui provider AWS, backend remoto, instancia RDS, subnet group, security group,
usuarios, credenciais ou backups reais.

## Validacao local

Na raiz do repositorio, com Terraform >= 1.6 e < 2.0:

```powershell
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false -input=false
terraform -chdir=infra validate
```

A pipeline usa Terraform 1.15.8 e nao solicita credenciais AWS.

O arquivo `terraform.tfvars.example` descreve os valores dos dois ambientes.
Copie para `terraform.tfvars` apenas se precisar testar ajustes locais; arquivos
de variaveis reais, estados, planos e dumps sao ignorados pelo Git.

## Limite desta validacao

O CI atual verifica a consistencia da estrutura e nao comprova existencia de
instancia, disponibilidade da versao/classe RDS ou permissoes. Ele nao executa
plan/apply nem testa conexao com banco.

Os campos de criptografia, backups e protecao contra exclusao sao intencoes
de configuracao. Eles so terao efeito quando os recursos correspondentes forem
implementados e implantados.

## Dependencias da fase AWS

1. Receber VPC e subnets privadas da infraestrutura Kubernetes.
2. Confirmar versao exata do PostgreSQL, classe e armazenamento disponiveis.
3. Implementar RDS, subnet group, security group e gestao de segredos.
4. Autorizar acesso de rede para API/Lambda, sem liberar o banco para a internet.
5. Criar bancos, roles e grants por ambiente com um processo de bootstrap.
6. Executar migrations controladas pelo repositorio da API.
7. Validar conexao, backup e restauracao.
8. Configurar backend remoto, OIDC e deploy automatico dos ambientes.

O RDS provisiona o servico; os dois bancos logicos e seus usuarios exigem
bootstrap SQL separado. Nao assumir que a criacao de uma instancia cria
automaticamente todos os bancos e grants planejados.

## Estado compartilhado

A proposta do laboratorio usa uma instancia RDS para dois bancos logicos.
A instancia precisa de um unico dono e estado Terraform. Nao aplique a mesma
instancia em dois estados, um por branch.

O fluxo de promocao da infraestrutura compartilhada e os estados das
configuracoes por ambiente serao definidos na implementacao do CD.
Mudancas no mesmo estado precisam de locking remoto e execucao serializada.

## Remocao futura

Antes da remocao apos a avaliacao, exportar dados necessarios, validar restauracao
e registrar snapshots a preservar. A protecao contra exclusao precisara de
uma alteracao deliberada para remover a instancia. Snapshots preservados devem
ser acompanhados e removidos quando nao forem mais necessarios.

Nenhum apply ou destroy foi executado neste PR.
