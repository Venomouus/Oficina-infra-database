import copy
import importlib.util
import os
from pathlib import Path
import subprocess
import time
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bootstrap", ROOT / "bootstrap.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


def contract():
    return {
        "contract_version": 1, "ssl_mode": "VerifyFull", "address": "127.0.0.1", "port": 5432,
        "planned_environments": {
            env: dict(branch=branch, database_name="oficina_" + env,
                      **{suffix + "_role": "oficina_" + env + "_" + suffix for suffix in b.ROLE_SUFFIXES})
            for env, branch in [("staging", "develop"), ("producao", "master")]
        }
    }


class ContractTests(unittest.TestCase):
    def test_invalid_contracts_are_rejected(self):
        cases = []
        data = contract(); data["contract_version"] = 2; cases.append(data)
        data = contract(); data["ssl_mode"] = "Disable"; cases.append(data)
        data = contract(); data["port"] = True; cases.append(data)
        data = contract(); data["planned_environments"]["staging"]["app_role"] = "postgres"; cases.append(data)
        data = contract(); data["planned_environments"]["staging"]["database_name"] = "evil'; DROP DATABASE postgres;"; cases.append(data)
        data = contract(); data["planned_environments"]["producao"] = copy.deepcopy(data["planned_environments"]["staging"]); cases.append(data)
        for data in cases:
            with self.subTest(data=data):
                with self.assertRaises(b.BootstrapError):
                    b.read_contract(data, "staging")

    def test_weak_or_ambiguous_passwords_are_rejected(self):
        for password in ("short", "a" * 129, " " * 32, "á" * 32):
            with self.assertRaises(b.BootstrapError):
                b.scram(password)

    def test_passwords_are_not_exposed_in_arguments_or_errors(self):
        runner = b.Psql(b.read_contract(contract(), "staging"), "", local_test=True)
        result = subprocess.CompletedProcess([], 1, "", "ERROR: 42501 senha-super-secreta")
        with patch.object(b.subprocess, "run", return_value=result) as run:
            with self.assertRaisesRegex(b.BootstrapError, "^psql falhou: SQLSTATE 42501$"):
                runner.run("postgres", "oficina_admin", "senha-super-secreta", "SELECT 1")
            args, kwargs = run.call_args
            self.assertNotIn("senha-super-secreta", " ".join(args[0]))
            self.assertEqual(kwargs["env"]["PGPASSWORD"], "senha-super-secreta")

    def test_tls_requires_ca_file(self):
        with self.assertRaises(b.BootstrapError):
            b.Psql(b.read_contract(contract(), "staging"), "missing-ca.pem")


class PermissionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container = "oficina-bootstrap-test-" + uuid.uuid4().hex[:12]
        cls.passwords = {key: uuid.uuid4().hex + "'$\\!" for key in (*b.ROLE_SUFFIXES, "admin")}
        cls.admin = "bootstrap_admin"
        cls.addClassCleanup(cls.cleanup)
        env = dict(os.environ, POSTGRES_PASSWORD=cls.passwords["admin"])
        subprocess.run(["docker", "run", "-d", "--rm", "--name", cls.container,
                        "--label", "oficina.bootstrap-test=" + cls.container,
                        "-e", "POSTGRES_PASSWORD", "postgres:16-alpine"],
                       env=env, check=True, capture_output=True, timeout=180)
        for _ in range(60):
            # O entrypoint inicia um servidor temporario somente por socket Unix.
            # Esperar TCP, igual ao Psql.run, evita liberar os testes durante o initdb.
            result = subprocess.run(["docker", "exec", cls.container, "pg_isready",
                                     "-h", "127.0.0.1", "-p", "5432", "-U", "postgres", "-d", "postgres"],
                                    capture_output=True, timeout=5)
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("PostgreSQL descartavel nao ficou pronto em TCP 127.0.0.1:5432.")
        cls.cfg = b.read_contract(contract(), "staging")
        cls.runner = b.Psql(cls.cfg, "", prefix=["docker", "exec", "-i", "--env", "PGPASSWORD",
                            "--env", "PGSSLMODE=disable", cls.container, "psql"], local_test=True)
        cls.runner.run("postgres", "postgres", cls.passwords["admin"],
                       f"CREATE ROLE {cls.admin} LOGIN CREATEDB CREATEROLE NOSUPERUSER PASSWORD "
                       + b.literal(b.scram(cls.passwords["admin"])) + ";")
        # Testar com CREATEROLE/CREATEDB, sem superuser nativo; nao simula toda a AWS.
        cls.runner.run("postgres", cls.admin, cls.passwords["admin"],
                       "SELECT current_user;")
        cls.prod = b.read_contract(contract(), "producao")
        b.prepare(cls.runner, cls.prod, cls.admin, cls.passwords)
        b.prepare(cls.runner, cls.cfg, cls.admin, cls.passwords)
        try:
            b.grant_access(cls.runner, cls.cfg, cls.admin, cls.passwords)
            raise AssertionError("Grants antes das migrations deveriam falhar.")
        except b.BootstrapError:
            pass
        state = cls.runner.run("postgres", cls.admin, cls.passwords["admin"],
            "SELECT rolcanlogin FROM pg_roles WHERE rolname='oficina_staging_app';")
        if state != "f":
            raise AssertionError("Login de runtime foi habilitado antes das migrations.")
        fixture = (ROOT / "tests/fixture.sql").read_text(encoding="utf-8")
        for cfg in (cls.cfg, cls.prod):
            cls.runner.run(cfg["database_name"], cfg["migrations_role"], cls.passwords["migrations"], fixture)
            b.grant_access(cls.runner, cfg, cls.admin, cls.passwords)

    @classmethod
    def cleanup(cls):
        inspect = subprocess.run(["docker", "inspect", "--format",
            '{{index .Config.Labels "oficina.bootstrap-test"}}', cls.container],
            capture_output=True, text=True, timeout=15)
        if inspect.returncode == 0 and inspect.stdout.strip() == cls.container:
            subprocess.run(["docker", "rm", "-f", "-v", cls.container],
                           capture_output=True, timeout=30, check=True)

    def query(self, role, sql, db=None):
        return self.runner.run(db or self.cfg["database_name"], self.cfg[role + "_role"],
                               self.passwords[role], sql)

    def denied(self, role, sql, db=None):
        with self.assertRaisesRegex(b.BootstrapError, "SQLSTATE 42501"):
            self.query(role, sql, db)

    def test_app_can_crud_business_data(self):
        self.query("app", """BEGIN;
          INSERT INTO "Servicos" VALUES ('22222222-2222-2222-2222-222222222222','Teste');
          UPDATE "Servicos" SET "Nome"='Alterado' WHERE "Id"='22222222-2222-2222-2222-222222222222';
          SELECT * FROM "Servicos";
          DELETE FROM "Servicos" WHERE "Id"='22222222-2222-2222-2222-222222222222';
          ROLLBACK;""")

    def test_auth_query_matches_lambda_and_denies_other_columns(self):
        self.assertIn("11111111", self.query("auth",
            """SELECT "Id", "Ativo" FROM "Clientes" WHERE "CpfCnpj" IN ('12345678909','123.456.789-09') LIMIT 2;"""))
        self.denied("auth", 'SELECT "Nome" FROM "Clientes";')
        self.denied("auth", 'SELECT * FROM "Clientes";')
        self.denied("auth", 'SELECT * FROM "OrdensServico";')
        self.denied("auth", 'UPDATE "Clientes" SET "Ativo"=false;')

    def test_runtime_cannot_ddl_truncate_or_modify_migration_history(self):
        for role in ("app", "auth"):
            self.denied(role, "CREATE TABLE public.invasao (id int);")
            self.denied(role, "CREATE TEMP TABLE invasao (id int);")
            self.denied(role, 'DROP TABLE "Clientes";')
            self.denied(role, 'TRUNCATE "Clientes";')
            self.denied(role, 'DELETE FROM "__EFMigrationsHistory";')
            self.denied(role, "CREATE ROLE invasao;")

    def test_environments_cannot_connect_to_each_other(self):
        for role in b.ROLE_SUFFIXES:
            self.assertEqual("f", self.runner.run("postgres", self.admin, self.passwords["admin"],
                "SELECT has_database_privilege(" + b.literal(self.cfg[role + "_role"]) + ", " +
                b.literal(self.prod["database_name"]) + ", 'CONNECT');"))
            with self.assertRaises(b.BootstrapError):
                self.query(role, "SELECT 1;", self.prod["database_name"])
            self.assertEqual("f", self.runner.run("postgres", self.admin, self.passwords["admin"],
                "SELECT has_database_privilege(" + b.literal(self.prod[role + "_role"]) + ", " +
                b.literal(self.cfg["database_name"]) + ", 'CONNECT');"))
            with self.assertRaises(b.BootstrapError):
                self.runner.run(self.cfg["database_name"], self.prod[role + "_role"],
                                self.passwords[role], "SELECT 1;")

    def test_runtime_cannot_assume_migration_role(self):
        for role in ("app", "auth"):
            self.denied(role, "SET ROLE oficina_staging_migrations;")

    def test_new_objects_are_closed_by_default(self):
        self.query("migrations", """CREATE TABLE future_private (id int);
          CREATE FUNCTION public.future_secret() RETURNS int LANGUAGE sql AS 'SELECT 42';""")
        try:
            for role in ("app", "auth"):
                self.denied(role, "SELECT * FROM future_private;")
                self.denied(role, "SELECT public.future_secret();")
        finally:
            self.query("migrations", "DROP TABLE future_private; DROP FUNCTION public.future_secret();")

    def test_repeated_bootstrap_preserves_data_and_passwords(self):
        before = self.query("app", 'SELECT count(*) FROM "Clientes";')
        b.prepare(self.runner, self.cfg, self.admin, self.passwords)
        b.grant_access(self.runner, self.cfg, self.admin, self.passwords)
        self.assertEqual(before, self.query("app", 'SELECT count(*) FROM "Clientes";'))
        self.query("auth", 'SELECT "Id" FROM "Clientes";')
        self.denied("app", 'SELECT * FROM "__EFMigrationsHistory";')

    def test_existing_owner_is_not_taken_over(self):
        # Banco preexistente de outro owner deve permanecer intocado.
        changed = copy.deepcopy(self.cfg)
        changed["database_name"] = "foreign_database"
        changed.update({suffix + "_role": "foreign_database_" + suffix for suffix in b.ROLE_SUFFIXES})
        self.runner.run("postgres", "postgres", self.passwords["admin"],
                        "CREATE DATABASE foreign_database OWNER postgres;")
        with self.assertRaises(b.BootstrapError):
            b.prepare(self.runner, changed, self.admin, self.passwords)
        self.assertEqual("postgres", self.runner.run("postgres", "postgres", self.passwords["admin"],
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='foreign_database';"))

    def test_reapply_removes_excess_column_grants(self):
        self.query("migrations", 'GRANT SELECT ("Nome") ON "Clientes" TO oficina_staging_auth;')
        self.query("auth", 'SELECT "Nome" FROM "Clientes";')
        b.grant_access(self.runner, self.cfg, self.admin, self.passwords)
        self.denied("auth", 'SELECT "Nome" FROM "Clientes";')

    @unittest.skipUnless(os.environ.get("BOOTSTRAP_MIGRATIONS_SQL"), "SQL real do EF nao informado")
    def test_real_ef_migrations_with_restricted_runtime(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["database_name"] = "ef_staging"
        cfg.update({suffix + "_role": "ef_staging_" + suffix for suffix in b.ROLE_SUFFIXES})
        b.prepare(self.runner, cfg, self.admin, self.passwords)
        sql = Path(os.environ["BOOTSTRAP_MIGRATIONS_SQL"]).read_text(encoding="utf-8-sig")
        self.runner.run(cfg["database_name"], cfg["migrations_role"], self.passwords["migrations"], sql)
        b.grant_access(self.runner, cfg, self.admin, self.passwords)
        history = self.runner.run(cfg["database_name"], cfg["migrations_role"], self.passwords["migrations"],
            'SELECT count(*) FROM "__EFMigrationsHistory";')
        self.assertGreaterEqual(int(history), 3)
        self.runner.run(cfg["database_name"], cfg["app_role"], self.passwords["app"], '''
            INSERT INTO "Clientes" ("Id","Nome","CpfCnpj","Telefone","Email","Ativo")
            VALUES ('33333333-3333-3333-3333-333333333333','Teste','12345678909','11999999999','teste@example.test',true);''')
        self.assertIn("33333333", self.runner.run(cfg["database_name"], cfg["auth_role"], self.passwords["auth"],
            '''SELECT "Id", "Ativo" FROM "Clientes" WHERE "CpfCnpj"='12345678909' LIMIT 2;'''))
        with self.assertRaisesRegex(b.BootstrapError, "SQLSTATE 42501"):
            self.runner.run(cfg["database_name"], cfg["app_role"], self.passwords["app"],
                            'DELETE FROM "__EFMigrationsHistory";')


if __name__ == "__main__":
    unittest.main()
