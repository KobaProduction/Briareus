"""Portable schema checks plus optional real-PostgreSQL migration acceptance.

By default no Docker, network, or existing database is used. If a local PostgreSQL
binary distribution is installed, auto mode starts an isolated native server.
Otherwise portable SQLite schema/contract tests run while PostgreSQL-only checks
are explicitly SKIPPED. External test databases and Docker require opt-in.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch
from uuid import uuid4

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from control_panel_api.infrastructure.crypto import FernetCredentialCipher
from control_panel_api.infrastructure.database import (
    Base,
    ControlPanelConfigRecord,
    InvocationRecord,
    create_database,
)
from control_panel_api.infrastructure.migrations import migration_config, run_migrations
from control_panel_api.infrastructure.repositories import SqlAlchemyInvocationRepository
from control_panel_api.infrastructure.schema_validation import validate_schema
from cryptography.fernet import Fernet
from sqlalchemy import Connection, Engine, Table, create_engine, event, inspect, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "deploy/services.json").is_file()
)
POSTGRES_IMAGE = "postgres:16-alpine"
REVISION = "0002_terminal_concurrency"


def docker(arguments: list[str], *, environment: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["docker", *arguments],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    if result.returncode:
        raise RuntimeError(f"Disposable PostgreSQL Docker command failed: {arguments[0]}")
    return result.stdout.strip()


def _pg_binary(name: str) -> str | None:
    directory = os.environ.get("BRIAREUS_TEST_PG_BIN_DIR", "").strip()
    if directory:
        binary = Path(directory) / name
        return str(binary) if binary.is_file() and os.access(binary, os.X_OK) else None
    return shutil.which(name)


def _native_admin(cls: type[PostgresMigrationAcceptance]) -> URL:
    initdb, pg_ctl = _pg_binary("initdb"), _pg_binary("pg_ctl")
    if not initdb or not pg_ctl:
        raise RuntimeError(
            "Native PostgreSQL requires initdb and pg_ctl; use a dedicated test installation"
        )
    temp = tempfile.TemporaryDirectory(prefix="briareus-postgres-test-")
    cls.addClassCleanup(temp.cleanup)
    data = Path(temp.name) / "data"
    socket = Path(temp.name) / "socket"
    socket.mkdir(mode=0o700)
    subprocess.run(
        [
            initdb,
            "--no-instructions",
            "--auth-local=trust",
            "--auth-host=reject",
            "-U",
            "postgres",
            "-D",
            str(data),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    options = f"-c listen_addresses='' -c unix_socket_directories={socket}"
    subprocess.run(
        [
            pg_ctl,
            "-D",
            str(data),
            "-o",
            options,
            "-l",
            str(Path(temp.name) / "postgres.log"),
            "-w",
            "start",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=45,
    )
    cls.addClassCleanup(_stop_native, pg_ctl, str(data))
    return URL.create(
        "postgresql+psycopg", username="postgres", database="postgres", query={"host": str(socket)}
    )


def _stop_native(pg_ctl: str, data: str) -> None:
    subprocess.run(
        [pg_ctl, "-D", data, "-m", "immediate", "-w", "stop"],
        check=True,
        stdout=subprocess.DEVNULL,
        timeout=30,
    )


def _external_admin() -> URL:
    raw = os.environ.get("BRIAREUS_TEST_POSTGRES_URL", "").strip()
    approved = os.environ.get("BRIAREUS_TEST_POSTGRES_ALLOW_CREATE", "") == "1"
    if not raw or not approved:
        raise ValueError(
            "External PostgreSQL requires a dedicated test URL and explicit "
            "BRIAREUS_TEST_POSTGRES_ALLOW_CREATE=1"
        )
    url = make_url(raw)
    if url.drivername != "postgresql+psycopg" or url.database != "briareus_test_admin":
        raise ValueError(
            "External PostgreSQL URL must use psycopg and database briareus_test_admin"
        )
    return url


def _docker_admin(cls: type[PostgresMigrationAcceptance]) -> URL:
    if shutil.which("docker") is None:
        raise RuntimeError("Docker mode explicitly requested but Docker CLI is unavailable")
    docker(["image", "inspect", POSTGRES_IMAGE])
    environment = dict(os.environ, POSTGRES_PASSWORD=secrets.token_urlsafe(40))
    cls.container_id = docker(
        [
            "run",
            "--detach",
            "--rm",
            "--pull",
            "never",
            "--name",
            "briareus-alembic-test-" + uuid4().hex,
            "--label",
            "briareus.test=alembic",
            "--tmpfs",
            "/var/lib/postgresql/data:rw",
            "--publish",
            "127.0.0.1::5432",
            "--env",
            "POSTGRES_PASSWORD",
            POSTGRES_IMAGE,
        ],
        environment=environment,
    )
    if not re.fullmatch(r"[a-f0-9]{64}", cls.container_id):
        raise RuntimeError("Docker did not return an exact disposable container ID")
    cls.addClassCleanup(cls.remove_container)
    port = int(docker(["port", cls.container_id, "5432/tcp"]).rsplit(":", 1)[1])
    return URL.create(
        "postgresql+psycopg",
        username="postgres",
        password=environment["POSTGRES_PASSWORD"],
        host="127.0.0.1",
        port=port,
        database="postgres",
    )


def _postgres_admin(cls: type[PostgresMigrationAcceptance]) -> URL:
    mode = os.environ.get("BRIAREUS_TEST_POSTGRES_MODE", "auto").strip().lower()
    if mode not in {"auto", "native", "external", "docker"}:
        raise ValueError("BRIAREUS_TEST_POSTGRES_MODE must be auto, native, external, or docker")
    if mode == "docker":
        return _docker_admin(cls)
    if mode == "external" or (mode == "auto" and os.environ.get("BRIAREUS_TEST_POSTGRES_URL")):
        return _external_admin()
    if mode == "native" or (_pg_binary("initdb") and _pg_binary("pg_ctl")):
        return _native_admin(cls)
    raise unittest.SkipTest(
        "Native PostgreSQL binaries unavailable. PostgreSQL-only checks skipped; "
        "install PostgreSQL or provide a dedicated test server."
    )


class PostgresMigrationAcceptance(unittest.TestCase):
    container_id: ClassVar[str] = ""
    admin: ClassVar[Engine]
    admin_url: ClassVar[URL]
    databases: ClassVar[set[str]] = set()
    database_name: str
    engine: Engine

    @classmethod
    def setUpClass(cls) -> None:
        cls.databases = set()
        cls.admin_url = _postgres_admin(cls)
        cls.admin = create_engine(cls.admin_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
        cls.addClassCleanup(cls.admin.dispose)
        cls.wait_ready()

    @classmethod
    def wait_ready(cls) -> None:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                with cls.admin.connect() as connection:
                    connection.execute(text("SELECT 1"))
                return
            except OperationalError:
                time.sleep(0.25)
        raise RuntimeError("Disposable PostgreSQL did not become ready")

    @classmethod
    def remove_container(cls) -> None:
        identity = docker(
            [
                "inspect",
                "--format",
                '{{index .Config.Labels "briareus.test"}}',
                cls.container_id,
            ]
        )
        if identity != "alembic":
            raise RuntimeError("Refusing to remove a container without the test owner label")
        docker(["rm", "--force", cls.container_id])

    def setUp(self) -> None:
        self.database_name = "briareus_alembic_test_" + uuid4().hex
        self.databases.add(self.database_name)
        with self.admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{self.database_name}"')
        self.engine = create_engine(
            self.admin_url.set(database=self.database_name), hide_parameters=True
        )
        self.addCleanup(self.remove_database)

    def remove_database(self) -> None:
        self.engine.dispose()
        if self.database_name not in self.databases or not re.fullmatch(
            r"briareus_alembic_test_[a-f0-9]{32}", self.database_name
        ):
            raise RuntimeError("Refusing to drop a database outside this test run")
        with self.admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{self.database_name}" WITH (FORCE)')
        self.databases.remove(self.database_name)

    def test_retention_commits_age_and_oldest_overflow_and_is_idempotent(self) -> None:
        run_migrations(self.engine)
        sessions = sessionmaker(self.engine, class_=Session)
        now = datetime.now(UTC)
        with sessions.begin() as session:
            session.add(
                ControlPanelConfigRecord(id=1, logging_retention_days=7, logging_max_records=100)
            )
            for index in range(108):
                session.add(
                    InvocationRecord(
                        id=f"{index:036d}",
                        module="test",
                        tool="test",
                        status="ok",
                        duration_ms=1,
                        occurred_at=now - timedelta(days=8 if index < 3 else 1),
                    )
                )
        repository = SqlAlchemyInvocationRepository(sessions)
        self.assertEqual(repository.cleanup(), 8)
        with sessions() as session:
            ids = list(session.scalars(select(InvocationRecord.id).order_by(InvocationRecord.id)))
        self.assertEqual(ids, [f"{index:036d}" for index in range(8, 108)])
        self.assertEqual(repository.cleanup(), 0)

    def revision(self) -> str:
        with self.engine.connect() as connection:
            return str(connection.scalar(text("SELECT version_num FROM alembic_version")))

    def persist_account(self) -> tuple[Table, str, str]:
        table = Base.metadata.tables["github_accounts"]
        identifier = str(uuid4())
        payload = FernetCredentialCipher(Fernet.generate_key().decode()).encrypt("keep-secret")
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            connection.execute(
                table.insert().values(
                    id=identifier,
                    alias="keep",
                    auth_type="github_token",
                    app_id="",
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                    encrypted_credential=payload,
                )
            )
        return table, identifier, payload

    def assert_persisted_account(self, table: Table, identifier: str, payload: str) -> None:
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.scalar(
                    select(table.c.encrypted_credential).where(table.c.id == identifier)
                ),
                payload,
            )

    def test_fresh_database_upgrades_to_the_exact_declared_schema(self) -> None:
        run_migrations(self.engine)
        self.assertEqual(self.revision(), REVISION)
        self.assertEqual(
            set(inspect(self.engine).get_table_names()),
            set(Base.metadata.tables) | {"alembic_version"},
        )
        with self.engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True, "compare_server_default": True}
            )
            self.assertEqual(compare_metadata(context, Base.metadata), [])

    def test_repeated_upgrade_preserves_encrypted_accounts(self) -> None:
        run_migrations(self.engine)
        table, identifier, payload = self.persist_account()
        run_migrations(self.engine)
        self.assert_persisted_account(table, identifier, payload)
        self.assertEqual(self.revision(), REVISION)

    def test_explicit_downgrade_and_upgrade_work_on_a_disposable_database(self) -> None:
        run_migrations(self.engine)
        with self.engine.begin() as connection:
            command.downgrade(migration_config(connection), "base")
        self.assertEqual(inspect(self.engine).get_table_names(), ["alembic_version"])
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM alembic_version")), 0)
        run_migrations(self.engine)
        self.assertEqual(self.revision(), REVISION)
        self.assertEqual(len(inspect(self.engine).get_table_names()), 13)

    def test_compatible_unversioned_postgres_is_adopted_without_rewriting_data(self) -> None:
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE runtime_settings DROP COLUMN terminal_max_concurrent_processes"
            )
        table, identifier, payload = self.persist_account()
        run_migrations(self.engine)
        self.assertEqual(self.revision(), REVISION)
        self.assert_persisted_account(table, identifier, payload)

    def test_partial_database_is_rejected_without_creating_other_tables(self) -> None:
        table = Base.metadata.tables["github_accounts"]
        table.create(self.engine)
        table, identifier, payload = self.persist_account()
        with self.assertRaises(RuntimeError):
            run_migrations(self.engine)
        self.assertEqual(inspect(self.engine).get_table_names(), ["github_accounts"])
        self.assert_persisted_account(table, identifier, payload)

    def test_incompatible_unversioned_schema_is_rejected_without_altering_it(self) -> None:
        Base.metadata.create_all(self.engine)
        table, identifier, payload = self.persist_account()
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE github_accounts ALTER COLUMN alias TYPE VARCHAR(127)"
            )
        with self.assertRaises(RuntimeError):
            run_migrations(self.engine)
        self.assertNotIn("alembic_version", inspect(self.engine).get_table_names())
        self.assert_persisted_account(table, identifier, payload)

    def test_unknown_newer_revision_is_rejected_without_rewriting_its_version(self) -> None:
        run_migrations(self.engine)
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num='9999_future'"))
        with self.assertRaises(CommandError):
            run_migrations(self.engine)
        self.assertEqual(self.revision(), "9999_future")

    def test_failed_upgrade_rolls_back_tables_and_version_together(self) -> None:
        def fail_creation(
            _connection: Connection,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            if "CREATE TABLE invocations" in statement:
                raise RuntimeError("Injected migration failure")

        event.listen(self.engine, "before_cursor_execute", fail_creation)
        try:
            with self.assertRaisesRegex(RuntimeError, "Injected migration failure"):
                run_migrations(self.engine)
        finally:
            event.remove(self.engine, "before_cursor_execute", fail_creation)
        self.assertEqual(inspect(self.engine).get_table_names(), [])

    def test_concurrent_startups_serialize_upgrade_and_record_one_head(self) -> None:
        barrier = threading.Barrier(2)

        def upgrade() -> None:
            barrier.wait(timeout=10)
            run_migrations(self.engine)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(upgrade) for _ in range(2)]
            for future in futures:
                future.result(timeout=45)
        self.assertEqual(self.revision(), REVISION)
        self.assertEqual(len(inspect(self.engine).get_table_names()), 13)


class SqliteMigrationAcceptance(PostgresMigrationAcceptance):
    """Run real Alembic upgrades on ephemeral SQLite, not just create_all()."""

    @classmethod
    def setUpClass(cls) -> None:
        """SQLite tests never create containers or connect to any service."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", hide_parameters=True)
        self.addCleanup(self.engine.dispose)

    def remove_database(self) -> None:
        """PostgreSQL database deletion has no SQLite counterpart."""

    @unittest.skip("PostgreSQL-only: pg_advisory_xact_lock startup serialization")
    def test_concurrent_startups_serialize_upgrade_and_record_one_head(self) -> None:
        """PostgreSQL-specific advisory-lock concurrency test."""

    def test_sqlite_file_serializes_two_concurrent_startups(self) -> None:
        """SQLite's write transaction, not PostgreSQL's advisory lock, provides isolation."""
        with tempfile.TemporaryDirectory(prefix="briareus-sqlite-concurrency-") as directory:
            engine, _sessions = create_database(
                "sqlite+pysqlite:///" + str(Path(directory) / "concurrent.sqlite3")
            )
            try:
                barrier = threading.Barrier(2)

                def upgrade() -> None:
                    barrier.wait(timeout=5)
                    run_migrations(engine)

                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [executor.submit(upgrade) for _ in range(2)]
                    for future in futures:
                        future.result(timeout=15)
                with engine.connect() as connection:
                    self.assertEqual(
                        connection.scalar(text("SELECT version_num FROM alembic_version")), REVISION
                    )
                    self.assertEqual(len(inspect(connection).get_table_names()), 13)
            finally:
                engine.dispose()

    def test_incompatible_unversioned_schema_is_rejected_without_altering_it(self) -> None:
        Base.metadata.create_all(self.engine)
        table, identifier, payload = self.persist_account()
        with self.engine.begin() as connection:
            from alembic.operations import Operations

            with (
                Operations.context(MigrationContext.configure(connection)) as operations,
                operations.batch_alter_table("github_accounts", recreate="always") as batch,
            ):
                batch.alter_column("alias", type_=sa.String(127), existing_type=sa.String(128))
        with self.assertRaises(RuntimeError):
            run_migrations(self.engine)
        self.assert_persisted_account(table, identifier, payload)


class PortableSchemaContracts(unittest.TestCase):
    """No external services; these do not claim to replace PostgreSQL migration tests."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        self.addCleanup(self.engine.dispose)

    def test_declared_schema_matches_in_memory_database(self) -> None:
        Base.metadata.create_all(self.engine)
        with self.engine.connect() as connection:
            validate_schema(connection, Base.metadata)
        self.assertEqual(set(inspect(self.engine).get_table_names()), set(Base.metadata.tables))

    def test_partial_schema_is_rejected_without_modifying_it(self) -> None:
        Base.metadata.tables["github_accounts"].create(self.engine)
        with self.engine.connect() as connection, self.assertRaises(RuntimeError):
            validate_schema(connection, Base.metadata)
        self.assertEqual(inspect(self.engine).get_table_names(), ["github_accounts"])

    def test_encrypt_and_persist_account_data(self) -> None:
        Base.metadata.create_all(self.engine)
        encrypted = FernetCredentialCipher(Fernet.generate_key().decode()).encrypt("fixture-secret")
        table = Base.metadata.tables["github_accounts"]
        with self.engine.begin() as connection:
            connection.execute(
                table.insert().values(
                    id=str(uuid4()),
                    alias="fixture",
                    auth_type="github_token",
                    app_id="",
                    enabled=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    encrypted_credential=encrypted,
                )
            )
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(select(table.c.encrypted_credential)), encrypted)
        self.assertNotIn("fixture-secret", encrypted)

    def test_retention_and_idempotence_without_postgres(self) -> None:
        Base.metadata.create_all(self.engine)
        sessions = sessionmaker(self.engine, class_=Session)
        now = datetime.now(UTC)
        with sessions.begin() as session:
            session.add(
                ControlPanelConfigRecord(id=1, logging_retention_days=7, logging_max_records=100)
            )
            for index in range(108):
                session.add(
                    InvocationRecord(
                        id=f"{index:036d}",
                        module="test",
                        tool="test",
                        status="ok",
                        duration_ms=1,
                        occurred_at=now - timedelta(days=8 if index < 3 else 1),
                    )
                )
        repository = SqlAlchemyInvocationRepository(sessions)
        self.assertEqual(repository.cleanup(), 8)
        self.assertEqual(repository.cleanup(), 0)

    def test_alembic_revision_chain_matches_declared_head(self) -> None:
        script = ScriptDirectory.from_config(migration_config())
        self.assertEqual(script.get_heads(), [REVISION])
        history = [revision.revision for revision in script.walk_revisions()]
        self.assertEqual(history, [REVISION, "0001_control_panel"])

    def test_auto_mode_without_postgres_skips_native_acceptance_without_docker(self) -> None:
        with (
            patch.dict(os.environ, {"BRIAREUS_TEST_POSTGRES_MODE": "auto"}, clear=True),
            patch(__name__ + "._pg_binary", return_value=None),
            patch(__name__ + ".docker", side_effect=AssertionError("Docker must not run")),
            self.assertRaises(unittest.SkipTest),
        ):
            _postgres_admin(PostgresMigrationAcceptance)

    def test_external_database_requires_explicit_test_namespace(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "BRIAREUS_TEST_POSTGRES_URL": "postgresql+psycopg://user@localhost/postgres",
                    "BRIAREUS_TEST_POSTGRES_ALLOW_CREATE": "1",
                },
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "briareus_test_admin"),
        ):
            _external_admin()
        with (
            patch.dict(
                os.environ,
                {
                    "BRIAREUS_TEST_POSTGRES_URL": "postgresql+psycopg://user@localhost/briareus_test_admin"
                },
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "ALLOW_CREATE"),
        ):
            _external_admin()

    def test_sqlite_factory_and_migrations_run_without_postgres(self) -> None:
        engine, sessions = create_database("sqlite+pysqlite:///:memory:")
        try:
            run_migrations(engine)
            self.assertEqual(len(inspect(engine).get_table_names()), 13)
            self.assertIsNotNone(sessions)
        finally:
            engine.dispose()


def selected_backend() -> str:
    """Select one or both migration engines; SQLite is the local default."""
    value = os.environ.get("BRIAREUS_TEST_DATABASE_BACKEND", "sqlite").strip().lower()
    if value not in {"sqlite", "postgresql", "both"}:
        raise ValueError("BRIAREUS_TEST_DATABASE_BACKEND must be sqlite, postgresql or both")
    return value


def main() -> int:
    backend = selected_backend()
    sqlite_selected = backend in {"sqlite", "both"}
    postgres_selected = backend in {"postgresql", "both"}
    suites = [unittest.defaultTestLoader.loadTestsFromTestCase(PortableSchemaContracts)]
    if sqlite_selected:
        suites.append(unittest.defaultTestLoader.loadTestsFromTestCase(SqliteMigrationAcceptance))
    if postgres_selected:
        suites.append(unittest.defaultTestLoader.loadTestsFromTestCase(PostgresMigrationAcceptance))
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(suites))
    skipped = [test.id() for test, _reason in result.skipped]
    sqlite_coverage = (
        sqlite_selected
        and result.wasSuccessful()
        and not any("setUpClass (__main__.SqliteMigrationAcceptance)" in value for value in skipped)
    )
    postgres_coverage = (
        postgres_selected
        and result.wasSuccessful()
        and not any("PostgresMigrationAcceptance" in value for value in skipped)
    )
    accepted = result.wasSuccessful() and (
        (not sqlite_selected or sqlite_coverage) and (not postgres_selected or postgres_coverage)
    )
    report = {
        "database_backend": backend,
        "postgres_mode": os.environ.get("BRIAREUS_TEST_POSTGRES_MODE", "auto"),
        "sqlite_migration_coverage": sqlite_coverage,
        "postgres_coverage": postgres_coverage,
        "tests_run": result.testsRun,
        "skipped_tests": skipped,
        "failed_tests": [test.id() for test, _trace in result.failures],
        "errored_tests": [test.id() for test, _trace in result.errors],
        "passed": accepted,
    }
    target = ROOT / "artifacts/briareus-alembic-postgres-acceptance.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
