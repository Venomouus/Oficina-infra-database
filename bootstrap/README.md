# Bootstrap PostgreSQL

Ferramenta Python 3.12 + psql 16, sem bibliotecas Python externas. Cria os bancos
logicos e roles do contrato database. Nao cria tabelas da API e nao aplica Terraform.
Migrations EF Core continuam sendo a fonte de verdade do schema.

## Entrega e limites

Codigo testado em PostgreSQL 16 descartavel, com um administrador
CREATEDB/CREATEROLE **sem superuser nativo**. Testes cobrem os dois ambientes,
reexecucao, DDL negado ao runtime, grants de colunas, isolamento de bancos,
defaults restritos e migrations reais do EF. Isso nao substitui validacao no RDS
de IAM, rds_superuser, TLS, rede e versao minor.

Nenhum banco/segredo AWS foi criado ou preenchido durante esta entrega.
DEPLOY_ENABLED permanece false e o workflow so executa testes.

## Credenciais e responsabilidades

| Uso | Role | Destino do segredo |
|---|---|---|
| Bootstrap | oficina_admin, mestre RDS | output bootstrap_secret_arn |
| API staging | oficina_staging_app | runtime_secret_arns.staging.app |
| Migrations staging | oficina_staging_migrations | runtime_secret_arns.staging.migrations |
| Auth staging | oficina_staging_auth | output authentication.secret_arns.database do serverless staging |
| API producao | oficina_producao_app | runtime_secret_arns.producao.app |
| Migrations producao | oficina_producao_migrations | runtime_secret_arns.producao.migrations |
| Auth producao | oficina_producao_auth | output authentication.secret_arns.database do serverless producao |

Nomes customizados seguem planned_environments no contrato. Os quatro containers
app/migrations pertencem a este Terraform; auth/database pertence ao serverless.
Valores app/migrations/auth usam JSON com username e password. Gerar senhas
distintas por role/ambiente, de 24 a 128 caracteres ASCII imprimiveis, sem espacos,
e guardar nos segredos antes do bootstrap. Nao colocar senhas em tfvars ou
aws_secretsmanager_secret_version: o Terraform nao consulta nem grava valores.

Bootstrap recebe senhas por variaveis de ambiente do processo, sem argumentos
de linha de comando ou arquivos de senha. O wrapper PowerShell pode pedi-las
sem eco/historico. Ele restaura as variaveis anteriores ao terminar.
Um runner privado pode injetar os mesmos valores a partir de Secrets Manager;
a automacao IAM/leitura/injecao ainda pertence a etapa de CD.

O usuario da API so deve poder obter seu segredo app. A Lambda ja le seu segredo
database. O job de migrations deve obter somente migrations do ambiente; apenas
a identidade administrativa de bootstrap recebe acesso ao segredo mestre.

## Duas fases

1. **prepare**: valida contrato, cria roles e banco sem tomar posse de banco de
   outro owner. migrations e owner do banco; nao tem CREATEDB, CREATEROLE,
   SUPERUSER, REPLICATION ou BYPASSRLS. app/auth nascem NOLOGIN.
   O administrador recebe SET na role migrations, sem heranca automatica.
   PUBLIC perde acesso ao banco e schema; runtime recebe CONNECT/USAGE, sem DDL/TEMP.
2. Executar migrations EF **como a role migrations do ambiente**.
3. **grants**: exige as oito tabelas com owner correto, aplica grants em transacao,
   remove grants excedentes (inclusive de colunas), habilita LOGIN de app/auth
   e verifica suas senhas por conexao real.

A API recebe SELECT/INSERT/UPDATE/DELETE somente nas oito tabelas de negocio.
Auth recebe SELECT apenas em Clientes(Id, Ativo, CpfCnpj), suficientes para a
consulta atual da Lambda. Nenhum runtime recebe acesso ao __EFMigrationsHistory,
TRUNCATE, DDL, outras roles ou banco do outro ambiente.

Objetos futuros nao concedem acesso automatico ao runtime/PUBLIC. Depois de
adicionar uma nova tabela a API, revisar TABLES em bootstrap.py e atualizar testes.
Funcoes/DDL customizados e sequences nao fazem parte do contrato atual (IDs UUID);
novas necessidades exigem grants explicitos. Rodar grants depois de cada migracao.

## Execucao futura na AWS

Requisitos: RDS/rede provisionados, Python/psql, CA oficial RDS, identidade
administrativa autorizada e acesso pela rede privada (por exemplo runner na VPC).
O bootstrap nao abre porta publica, cria bastion ou altera SGs. Um terminal
fora da VPC nao acessara o RDS privado apenas por ter sua senha.

Obter somente o output publico database (nao tfstate):

```powershell
$contract = terraform -chdir=infra output -json database
if ($LASTEXITCODE -ne 0) { throw 'Falha ao obter contrato do banco.' }
[IO.File]::WriteAllText((Join-Path (Get-Location) 'database.generated.json'), ($contract -join "`n"), [Text.UTF8Encoding]::new($false))
```

Baixar/conferir o [bundle CA oficial do RDS](https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem)
e mantê-lo no runner. Usar hostname original do RDS: TLS verify-full verifica CA
e nome; nao substituir o hostname por localhost/IP de tunel. A CLI publica nao
permite desativar TLS.

Na raiz do repositorio, **somente na etapa de provisionamento**:

```powershell
./scripts/Invoke-Bootstrap.ps1 -Contract ./database.generated.json -Environment staging -Phase prepare -SslRootCert ./config/global-bundle.pem
# Executar migrations da API com oficina_staging_migrations.
./scripts/Invoke-Bootstrap.ps1 -Contract ./database.generated.json -Environment staging -Phase grants -SslRootCert ./config/global-bundle.pem
```

O wrapper pede quatro senhas se ainda nao estiverem no ambiente do processo.
Usar as senhas previamente guardadas nos segredos, nao criar outras a cada fase.
O usuario mestre padrao e oficina_admin; BOOTSTRAP_ADMIN_USERNAME permite
substitui-lo quando o contrato administrativo exigir.

Em runner automatizado, invocar diretamente:

```text
python bootstrap/bootstrap.py --contract database.generated.json --environment staging --phase prepare --ssl-root-cert config/global-bundle.pem
```

Variaveis obrigatorias: BOOTSTRAP_ADMIN_PASSWORD, BOOTSTRAP_MIGRATIONS_PASSWORD,
BOOTSTRAP_APP_PASSWORD, BOOTSTRAP_AUTH_PASSWORD. Repetir por ambiente com
credenciais correspondentes. A funcao local_test existe apenas no harness
de testes; nao e opcao da CLI.

A aplicacao ainda executa Database.Migrate() no startup. Separar esse comportamento
no repositorio Oficina-Mecanica ANTES de usar a credencial app no deploy.
Nao contornar a falha de migrations concedendo DDL ao runtime.

## Reexecucao e falhas

Executar serialmente por ambiente. CREATE DATABASE nao permite uma transacao
abrangendo toda a preparacao. Uma falha pode deixar roles/banco criados; corrigir
a causa e repetir prepare, migrations pendentes e grants. Nao apagar bancos para
tentar novamente. A fase grants e transacional para ACLs, mas a habilitacao de
LOGIN ocorre em outra conexao; repetir a fase se essa ultima etapa falhar.

Reexecucao nao apaga dados, nao substitui owners e nao altera senhas de roles
existentes. migrations verifica sua senha em prepare; app/auth verificam em grants.
Senha diferente do segredo falha; recuperar a credencial correta ou executar
rotacao administrativa planejada, sem assumir que prepare rotaciona senhas.
Rotacao automatica nao esta implementada. Roles com privilegios elevados ou
membros de outras roles sao rejeitadas por prepare.

A CLI nao imprime SQL, senhas, verificadores SCRAM ou stderr bruto. A senha nova
e convertida em verificador SCRAM no cliente antes do CREATE ROLE. Esse
verificador tambem deve ser protegido; nao habilitar eco SQL/dumps de processo
ou logging detalhado de statements de administracao. Erros mostram SQLSTATE
quando disponivel; falhas na conexao podem nao fornecer esse codigo ao psql.

Remocao de bancos/roles nao faz parte da ferramenta. Revisar backups e dependencias
separadamente. Secrets Manager tem janela de recuperacao de 30 dias.

## Testar sem AWS

Docker Desktop com Linux containers e Python 3.12:

```powershell
python -m unittest discover -s bootstrap/tests -v
```

O harness cria um container postgres:16-alpine sem publicar portas ou montar
volumes do usuario. Remove somente o container com nome/label exclusivos do teste.
Usa fixture reduzida de permissoes; ela nunca deve ser aplicada em producao.

A CI tambem gera SQL das migrations reais de Oficina-Mecanica na revisao
c9733c35372124e15fe470ca3e8373a86c3f0e53 e testa como migrations, seguido de
INSERT como app e consulta como auth. Atualizar esse pin quando mudar o schema.
Nao usa HEAD remoto mutavel nem inicia a API.

Para incluir esse teste adicional localmente, gerar o SQL com dotnet ef migrations
script no repositorio da API e indicar seu caminho:

```powershell
$env:BOOTSTRAP_MIGRATIONS_SQL = 'CAMINHO_ABSOLUTO_DO_SQL_GERADO'
python -m unittest discover -s bootstrap/tests -v
Remove-Item Env:BOOTSTRAP_MIGRATIONS_SQL
```

Sem esse arquivo, o teste de migrations reais fica marcado como skipped; os
demais continuam executando. CI exige esse arquivo e executa todos os 14 testes.

Referencias:
[roles PostgreSQL 16](https://www.postgresql.org/docs/16/role-attributes.html),
[GRANT](https://www.postgresql.org/docs/16/sql-grant.html),
[default privileges](https://www.postgresql.org/docs/16/sql-alterdefaultprivileges.html),
[rds_superuser](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.Roles.rds_superuser.html).
