from __future__ import annotations

import os
import re
import shutil
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from alembic import command
from alembic.script import Script, ScriptDirectory
from control_panel_api.infrastructure.database import Base, create_database
from control_panel_api.infrastructure.migrations import migration_config, run_migrations
from control_panel_api.settings import ControlPanelSettings
from sqlalchemy import Engine, inspect
from sqlalchemy.engine import make_url


class ControlPanelPostgresContracts(unittest.TestCase):
    def test_runtime_uses_postgres_and_preserves_reserved_characters_in_credentials(self) -> None:
        with patch.dict(
            os.environ, {"CONTROL_PANEL_DATABASE_PATH": "/retired.sqlite3"}, clear=True
        ):
            settings = ControlPanelSettings(
                postgres_username="briareus-owner",
                postgres_password="p@ss:/% word",
                postgres_database="briareus",
            )
        url = make_url(settings.database_url)
        self.assertEqual(url.drivername, "postgresql+psycopg")
        self.assertEqual((url.host, url.port), ("postgres", 5432))
        self.assertEqual(url.username, "briareus-owner")
        self.assertEqual(url.password, "p@ss:/% word")
        self.assertEqual(url.database, "briareus")
        self.assertNotIn("database_path", ControlPanelSettings.model_fields)

    def test_missing_postgres_password_fails_bootstrap_without_printing_other_secrets(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = ControlPanelSettings(
                encryption_key="keep-encryption-secret",
                service_token="keep-service-secret",
            )
        with self.assertRaisesRegex(ValueError, "POSTGRES_PASSWORD") as raised:
            settings.validate_bootstrap()
        self.assertNotIn("keep-", str(raised.exception))

    def test_sqlite_backend_persists_real_migrations_in_an_isolated_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "control panel test.sqlite3"
            settings = ControlPanelSettings(database_backend="sqlite", sqlite_path=str(target))
            self.assertEqual(make_url(settings.database_url).database, str(target))
            engine, sessions = create_database(settings.database_url)
            try:
                run_migrations(engine)
                self.assertEqual(len(inspect(engine).get_table_names()), 13)
                self.assertIsNotNone(sessions)
            finally:
                engine.dispose()
            reopened, _ = create_database(settings.database_url)
            try:
                self.assertEqual(len(inspect(reopened).get_table_names()), 13)
                run_migrations(reopened)
            finally:
                reopened.dispose()

    def test_sqlite_requires_an_explicit_path_and_not_a_postgres_password(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = ControlPanelSettings(
                database_backend="sqlite",
                sqlite_path=":memory:",
                encryption_key="fixture-encryption-key",
                service_token="fixture-service-token",
            )
        settings.validate_bootstrap()
        self.assertEqual(settings.database_url, "sqlite+pysqlite:///:memory:")
        with self.assertRaisesRegex(ValueError, "CONTROL_PANEL_SQLITE_PATH"):
            ControlPanelSettings(database_backend="sqlite").validate_bootstrap()

    def test_postgres_connection_target_is_configurable(self) -> None:
        settings = ControlPanelSettings(
            postgres_host="127.0.0.1",
            postgres_port=15432,
            postgres_username="tester",
            postgres_password="secret",
            postgres_database="fixture",
        )
        url = make_url(settings.database_url)
        self.assertEqual((url.host, url.port, url.database), ("127.0.0.1", 15432, "fixture"))

    def test_sqlite_shorthand_uses_the_same_supported_driver(self) -> None:
        engine, _sessions = create_database("sqlite:///:memory:")
        try:
            run_migrations(engine)
            self.assertEqual(len(inspect(engine).get_table_names()), 13)
        finally:
            engine.dispose()

    def test_unsupported_database_backend_fails_explicitly(self) -> None:
        with self.assertRaisesRegex(ValueError, "PostgreSQL/psycopg or SQLite/pysqlite"):
            create_database("mysql+pymysql://invalid.invalid/fixture")

    def test_migrations_refuse_unsupported_database_before_opening_a_transaction(self) -> None:
        engine = Mock(spec=Engine)
        engine.dialect = Mock()
        engine.dialect.name = "mysql"
        with self.assertRaisesRegex(ValueError, "require PostgreSQL or SQLite"):
            run_migrations(engine)
        engine.begin.assert_not_called()

    def test_packaged_revisions_have_one_ordered_head(self) -> None:
        scripts = ScriptDirectory.from_config(migration_config())
        self.assertEqual(scripts.get_heads(), ["0002_terminal_concurrency"])
        revision = scripts.get_revision("head")
        assert revision is not None
        self.assertEqual(revision.down_revision, "0001_control_panel")

    def test_initial_revision_renders_complete_postgres_ddl_without_a_database(self) -> None:
        output = StringIO()
        command.upgrade(migration_config(output_buffer=output), "head", sql=True)
        ddl = output.getvalue()
        created = set(re.findall(r"CREATE TABLE ([a-z_]+)\s*\(", ddl))
        self.assertEqual(created - {"alembic_version"}, set(Base.metadata.tables))
        self.assertEqual(len(created), 13)
        self.assertNotIn("CREATE TABLE briareus_identity_sessions", ddl)
        self.assertNotIn("CREATE TABLE briareus_identity_transactions", ddl)
        self.assertNotIn("CREATE TABLE oauth_sessions", ddl)
        self.assertIn("0001_control_panel", ddl)
        self.assertNotIn("sqlite", ddl.lower())

    def test_packaged_template_can_generate_the_next_versioned_revision(self) -> None:
        configuration = migration_config()
        location = configuration.get_main_option("script_location")
        assert location is not None
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "alembic"
            shutil.copytree(location, target)
            configuration.set_main_option("script_location", str(target))
            revision = command.revision(
                configuration, message="Add audit lookup", rev_id="0002_test"
            )
            assert isinstance(revision, Script)
            self.assertEqual(revision.down_revision, "0002_terminal_concurrency")
            content = Path(revision.path).read_text()
            compile(content, revision.path, "exec")
            self.assertEqual(ScriptDirectory.from_config(configuration).get_heads(), ["0002_test"])
