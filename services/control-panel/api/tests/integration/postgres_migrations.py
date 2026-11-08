"""Explicit real-PostgreSQL acceptance; run with frozen project dependencies.

This entrypoint creates one disposable, tmpfs-backed PostgreSQL container and
never attaches it to an application network or mounts an existing volume.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.util.exc import CommandError
from control_panel_api.infrastructure.crypto import FernetCredentialCipher
from control_panel_api.infrastructure.database import (
    Base,
    ControlPanelConfigRecord,
    InvocationRecord,
)
from control_panel_api.infrastructure.migrations import migration_config, run_migrations
from control_panel_api.infrastructure.repositories import SqlAlchemyInvocationRepository
from cryptography.fernet import Fernet
from sqlalchemy import Connection, Engine, Table, create_engine, event, inspect, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "deploy/services.json").is_file()
)
POSTGRES_IMAGE = "postgres:16-alpine"
REVISION = "0001_control_panel"


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


class PostgresMigrationAcceptance(unittest.TestCase):
    container_id: ClassVar[str] = ""
    admin: ClassVar[Engine]
    admin_url: ClassVar[URL]
    databases: ClassVar[set[str]] = set()
    database_name: str
    engine: Engine

    @classmethod
    def setUpClass(cls) -> None:
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
        cls.admin_url = URL.create(
            "postgresql+psycopg",
            username="postgres",
            password=environment["POSTGRES_PASSWORD"],
            host="127.0.0.1",
            port=port,
            database="postgres",
        )
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


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PostgresMigrationAcceptance)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {
        "postgres_image": POSTGRES_IMAGE,
        "tests_run": result.testsRun,
        "failed_tests": [test.id() for test, _trace in result.failures],
        "errored_tests": [test.id() for test, _trace in result.errors],
        "passed": result.wasSuccessful(),
    }
    target = ROOT / "artifacts/briareus-alembic-postgres-acceptance.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
