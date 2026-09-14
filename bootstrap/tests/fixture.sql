-- Fixture de PERMISSOES, nao schema de producao. EF Core continua fonte de verdade.
CREATE TABLE "Clientes" ("Id" uuid PRIMARY KEY, "CpfCnpj" text, "Ativo" boolean, "Nome" text);
CREATE TABLE "Servicos" ("Id" uuid PRIMARY KEY, "Nome" text);
CREATE TABLE "Veiculos" ("Id" uuid PRIMARY KEY);
CREATE TABLE "PecasInsumos" ("Id" uuid PRIMARY KEY);
CREATE TABLE "OrdensServico" ("Id" uuid PRIMARY KEY);
CREATE TABLE "OrdemServicoServico" ("Id" uuid PRIMARY KEY);
CREATE TABLE "OrdemServicoPeca" ("Id" uuid PRIMARY KEY);
CREATE TABLE "HistoricoStatusOrdemServico" ("Id" uuid PRIMARY KEY);
CREATE TABLE "__EFMigrationsHistory" ("MigrationId" text PRIMARY KEY, "ProductVersion" text);
INSERT INTO "Clientes" VALUES ('11111111-1111-1111-1111-111111111111','12345678909',true,'Cliente de teste');
