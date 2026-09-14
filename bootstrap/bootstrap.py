"""Bootstrap PostgreSQL 16. Somente stdlib + psql; nao cria tabelas de negocio."""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import subprocess


TABLES = (
    "Clientes", "Veiculos", "Servicos", "PecasInsumos", "OrdensServico",
    "OrdemServicoServico", "OrdemServicoPeca", "HistoricoStatusOrdemServico",
)
ROLE_SUFFIXES = ("app", "auth", "migrations")


class BootstrapError(RuntimeError):
    pass


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,62}", value):
        raise BootstrapError("Identificador PostgreSQL invalido.")
    return '"' + value + '"'


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def scram(password: str) -> str:
    # ASCII evita ambiguidades de SASLprep. Senhas geradas no Secrets Manager
    # devem usar este mesmo contrato. O verificador tambem e dado sensivel.
    if not 24 <= len(password) <= 128 or any(ord(c) < 33 or ord(c) > 126 for c in password):
        raise BootstrapError("Senha deve ter 24 a 128 caracteres ASCII imprimiveis, sem espacos.")
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("ascii"), salt, 4096)
    client = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored = hashlib.sha256(client).digest()
    server = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    enc = lambda b: base64.b64encode(b).decode("ascii")
    return f"SCRAM-SHA-256$4096:{enc(salt)}${enc(stored)}:{enc(server)}"


def read_contract(data: dict, environment: str) -> dict:
    if data.get("contract_version") != 1 or data.get("ssl_mode") != "VerifyFull":
        raise BootstrapError("Esperado output database v1 com ssl_mode VerifyFull.")
    envs = data.get("planned_environments", {})
    if set(envs) != {"staging", "producao"} or environment not in envs:
        raise BootstrapError("Contrato exige staging e producao.")
    names = []
    for name, config in envs.items():
        db = config.get("database_name")
        identifier(db)
        if len(db) > 32 or config.get("branch") != {"staging": "develop", "producao": "master"}[name]:
            raise BootstrapError("Banco/branch incoerente no contrato.")
        for suffix in ROLE_SUFFIXES:
            if config.get(suffix + "_role") != db + "_" + suffix:
                raise BootstrapError("Role diverge do contrato do banco.")
            identifier(config[suffix + "_role"])
        names.append(db)
    if len(set(names)) != 2:
        raise BootstrapError("Os ambientes devem ter bancos diferentes.")
    address, port = data.get("address"), data.get("port")
    if not isinstance(address, str) or not re.fullmatch(r"[a-zA-Z0-9.-]+", address):
        raise BootstrapError("Endereco PostgreSQL invalido.")
    if type(port) is not int or not 1 <= port <= 65535:
        raise BootstrapError("Porta invalida.")
    return dict(envs[environment], address=address, port=port)


class Psql:
    def __init__(self, config: dict, ssl_root_cert: str, prefix=None, local_test=False):
        self.config = config
        self.prefix = prefix or ["psql"]
        self.ssl_mode = "disable" if local_test else "verify-full"
        self.cert = ssl_root_cert
        if not local_test and not Path(ssl_root_cert).is_file():
            raise BootstrapError("Informe o bundle CA do RDS em --ssl-root-cert.")

    def run(self, database: str, username: str, password: str, sql: str) -> str:
        identifier(database)
        identifier(username)
        env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
        env.update(PGPASSWORD=password, PGSSLMODE=self.ssl_mode, PGSSLROOTCERT=self.cert,
                   PGCONNECT_TIMEOUT="10", PGAPPNAME="oficina-bootstrap", PGCLIENTENCODING="UTF8")
        args = self.prefix + ["-X", "-w", "-q", "-A", "-t",
                              "-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=sqlstate",
                              "-h", self.config["address"], "-p", str(self.config["port"]),
                              "-U", username, "-d", database]
        try:
            result = subprocess.run(args, input=sql, text=True, encoding="utf-8",
                                    capture_output=True, env=env, timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise BootstrapError("Nao foi possivel executar psql; confira instalacao e conectividade.") from None
        if result.returncode:
            # Nao repassar SQL, verificador SCRAM, senha ou saida arbitraria.
            state = re.search(r"(?:ERROR|FATAL):\s+([0-9A-Z]{5})\b", result.stderr)
            raise BootstrapError("psql falhou: SQLSTATE " + (state[1] if state else "indisponivel"))
        return result.stdout.strip()


def prepare(psql: Psql, cfg: dict, admin: str, passwords: dict) -> None:
    db, mig, app, auth = (cfg[k] for k in ("database_name", "migrations_role", "app_role", "auth_role"))
    for name in (db, mig, app, auth, admin):
        identifier(name)
    if admin in (mig, app, auth):
        raise BootstrapError("Bootstrap exige identidade administrativa separada.")
    # Validar TODAS as senhas antes de qualquer alteracao.
    verifiers = {suffix: scram(passwords[suffix]) for suffix in ROLE_SUFFIXES}
    admin_password = passwords["admin"]
    sql = [
        "SET standard_conforming_strings = on;",
        "SELECT pg_advisory_lock(hashtextextended(" + literal("oficina-bootstrap:" + db) + ", 0));",
        """DO $$ BEGIN
          IF current_setting('server_version_num')::int NOT BETWEEN 160000 AND 169999 THEN
            RAISE EXCEPTION 'PostgreSQL 16 obrigatorio';
          END IF;
        END $$;""",
    ]
    for suffix in ROLE_SUFFIXES:
        role = cfg[suffix + "_role"]
        login = "LOGIN" if suffix == "migrations" else "NOLOGIN"
        sql.append(f"""DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = {literal(role)}) THEN
            CREATE ROLE {identifier(role)} {login} NOSUPERUSER NOCREATEDB NOCREATEROLE
              NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {literal(verifiers[suffix])};
          ELSIF EXISTS (SELECT FROM pg_roles WHERE rolname = {literal(role)}
              AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)) THEN
            RAISE EXCEPTION 'Role existente com privilegios elevados';
          END IF;
          IF EXISTS (SELECT FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
                     WHERE r.rolname={literal(role)}) THEN
            RAISE EXCEPTION 'Role de workload nao pode herdar outras roles';
          END IF;
        END $$;""")
    sql += [
        f"GRANT {identifier(mig)} TO {identifier(admin)} WITH SET TRUE, INHERIT FALSE;",
        f"""DO $$ BEGIN
          IF EXISTS (SELECT FROM pg_database d JOIN pg_roles r ON r.oid=d.datdba
                     WHERE d.datname={literal(db)} AND r.rolname<>{literal(mig)}) THEN
            RAISE EXCEPTION 'Banco existente possui outro owner';
          END IF;
        END $$;""",
        f"SELECT format('CREATE DATABASE %I OWNER %I TEMPLATE template0', {literal(db)}, {literal(mig)}) "
        f"WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname={literal(db)})\n\\gexec",
        f"SET ROLE {identifier(mig)};",
        f"REVOKE ALL ON DATABASE {identifier(db)} FROM PUBLIC;",
        f"GRANT CONNECT ON DATABASE {identifier(db)} TO {identifier(admin)}, {identifier(mig)};",
        "RESET ROLE;",
    ]
    psql.run("postgres", admin, admin_password, "\n".join(sql))
    # Acesso como migrations confirma a senha existente; reexecucao nao rotaciona credenciais.
    schema_sql = f"""
      BEGIN;
      REVOKE ALL ON DATABASE {identifier(db)} FROM {identifier(app)}, {identifier(auth)};
      GRANT CONNECT ON DATABASE {identifier(db)} TO {identifier(app)}, {identifier(auth)};
      REVOKE ALL ON SCHEMA public FROM PUBLIC, {identifier(app)}, {identifier(auth)};
      GRANT USAGE ON SCHEMA public TO {identifier(app)}, {identifier(auth)};
      ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC, {identifier(app)}, {identifier(auth)};
      ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC, {identifier(app)}, {identifier(auth)};
      ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
      COMMIT;
    """
    psql.run(db, mig, passwords["migrations"], schema_sql)


def grant_access(psql: Psql, cfg: dict, admin: str, passwords: dict) -> None:
    db, mig, app, auth = (cfg[k] for k in ("database_name", "migrations_role", "app_role", "auth_role"))
    # Fail closed: nao habilitar logins antes de migrations/grants completos.
    sql = ["BEGIN;"]
    for table in TABLES:
        sql.append(f"""DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_roles r ON r.oid=c.relowner WHERE n.nspname='public'
            AND c.relname={literal(table)} AND c.relkind IN ('r','p') AND r.rolname={literal(mig)}) THEN
            RAISE EXCEPTION 'Tabela ausente ou owner incorreto; executar migrations primeiro';
          END IF;
        END $$;""")
    sql += [
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, {identifier(app)}, {identifier(auth)};",
        # REVOKE de tabela nao remove grants antigos em colunas.
        f"""SELECT format('REVOKE ALL (%s) ON TABLE %I.%I FROM PUBLIC, %I, %I',
          string_agg(format('%I', a.attname), ', ' ORDER BY a.attnum), n.nspname, c.relname,
          {literal(app)}, {literal(auth)})
          FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
          JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')
          AND a.attnum>0 AND NOT a.attisdropped GROUP BY n.nspname,c.relname
          \\gexec""",
        f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, {identifier(app)}, {identifier(auth)};",
        f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, {identifier(app)}, {identifier(auth)};",
    ]
    for table in TABLES:
        sql.append(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public."{table}" TO {identifier(app)};')
    sql += [
        f'GRANT SELECT ("Id", "Ativo", "CpfCnpj") ON TABLE public."Clientes" TO {identifier(auth)};',
        "COMMIT;",
    ]
    psql.run(db, mig, passwords["migrations"], "\n".join(sql))
    psql.run("postgres", admin, passwords["admin"],
             f"BEGIN; ALTER ROLE {identifier(app)} LOGIN; ALTER ROLE {identifier(auth)} LOGIN; COMMIT;")
    for suffix in ("app", "auth"):
        psql.run(db, cfg[suffix + "_role"], passwords[suffix], "SELECT 1;")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, help="JSON do output database, nunca tfstate")
    parser.add_argument("--environment", required=True, choices=["staging", "producao"])
    parser.add_argument("--phase", required=True, choices=["prepare", "grants"])
    parser.add_argument("--ssl-root-cert", required=True)
    args = parser.parse_args()
    try:
        cfg = read_contract(json.loads(Path(args.contract).read_text(encoding="utf-8-sig")), args.environment)
        admin = os.environ.get("BOOTSTRAP_ADMIN_USERNAME", "oficina_admin")
        identifier(admin)
        needed = ROLE_SUFFIXES + ("admin",)
        passwords = {name: os.environ["BOOTSTRAP_" + name.upper() + "_PASSWORD"] for name in needed}
        if any(not value for value in passwords.values()):
            raise BootstrapError("Credencial ausente.")
        psql = Psql(cfg, args.ssl_root_cert)
        if args.phase == "prepare":
            prepare(psql, cfg, admin, passwords)
        else:
            grant_access(psql, cfg, admin, passwords)
        print(f"Fase {args.phase} concluida para {args.environment}.")
        return 0
    except (BootstrapError, KeyError, ValueError, OSError) as error:
        # Nao imprimir valores do JSON ou variaveis de ambiente em erros de parsing.
        print(str(error) if isinstance(error, BootstrapError) else "Configuracao/credenciais invalidas ou ausentes.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
