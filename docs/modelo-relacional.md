# Modelo relacional e migracoes

A fonte de verdade do schema e o EF Core em Oficina-Mecanica. Este Terraform provisiona a instancia; nao recria tabelas com SQL paralelo nem aplica migrations.

## Entidades existentes

| Tabela | Conteudo e integridade |
|---|---|
| Clientes | Id UUID, nome, CPF/CNPJ unico, contato e Ativo |
| Veiculos | ClienteId, placa unica, marca/modelo/ano; FK cliente com exclusao restrita |
| Servicos | Catalogo, preco decimal e flag Ativo |
| PecasInsumos | Codigo unico, preco decimal, estoque e Ativo |
| OrdensServico | Cliente/veiculo, numero unico, status, valores e datas; Versao como token de concorrencia |
| OrdemServicoServico | Itens com nome/preco registrados na OS; FK servico restrita |
| OrdemServicoPeca | Quantidade e preco registrados na OS; FK peca restrita |
| HistoricoStatusOrdemServico | Sequencia, status e datas por OS; unicidade de (OrdemServicoId, Sequencia), checks temporais e indice por status/inicio |

Os itens e o historico pertencem a OS e possuem cascade de exclusao por essa relacao. Os valores monetarios usam decimal de precisao definida. Os nomes/precos dos itens preservam o orcamento registrado mesmo se o catalogo mudar.

## Fluxo e historico

A criacao permanece em **Aguardando Aprovacao**, conforme a decisao funcional. A aprovacao registra a resposta do orcamento e inicia a execucao no fluxo atual. Nao inventar um periodo de diagnostico que a OS nao percorreu.

Periodos antigos sem inicio conhecido ou ainda abertos exigem tratamento explicito nas metricas; nao assumir duracao zero nem preencher datas ficticias. O historico persistido e o token de concorrencia ja pertencem a API, nao sao implementacoes deste Terraform.

## Ambientes e acesso

O bootstrap deve criar bancos separados, por exemplo:

| Ambiente | Banco | Roles planejadas |
|---|---|---|
| staging / develop | oficina_staging | oficina_staging_app, oficina_staging_auth, oficina_staging_migrations |
| producao / master | oficina_producao | oficina_producao_app, oficina_producao_auth, oficina_producao_migrations |

Conceder DML a API, leitura limitada de clientes ao autenticador e DDL somente a migrations. Configurar grants atuais e default privileges, revogando o acesso PUBLIC entre ambientes. A conta mestre serve somente a bootstrap/administracao controlada.

Migrations devem partir do mesmo codigo revisado e rodar por ambiente antes do rollout. A chamada atual de migrations no startup da API precisa ser separada antes de restringir a role de runtime.

Indices de consultas por cliente/status/data e concorrencia de estoque precisam ser avaliados com os fluxos reais e EXPLAIN; a presenca de indices e tests unitarios nao comprova desempenho. Testar restauração em um banco separado e conferir OS, itens e historico antes de gravar a evidencia de recuperacao.
