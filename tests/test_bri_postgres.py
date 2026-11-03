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
from sqlalchemy import Engine
from sqlalchemy.engine import make_url

from common.settings import ControlPanelSettings
from control_panel_api.infrastructure.database import Base, create_database
from control_panel_api.infrastructure.migrations import migration_config, run_migrations


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
                session_secret="keep-session-secret",
            )
        with self.assertRaisesRegex(ValueError, "POSTGRES_PASSWORD") as raised:
            settings.validate_bootstrap()
        self.assertNotIn("keep-", str(raised.exception))

    def test_runtime_rejects_sqlite_instead_of_falling_back(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires PostgreSQL"):
            create_database("sqlite://")

    def test_migrations_refuse_another_database_before_opening_a_transaction(self) -> None:
        engine = Mock(spec=Engine)
        engine.dialect = Mock()
        engine.dialect.name = "sqlite"
        with self.assertRaisesRegex(ValueError, "require PostgreSQL"):
            run_migrations(engine)
        engine.begin.assert_not_called()

    def test_packaged_revisions_have_one_initial_head(self) -> None:
        scripts = ScriptDirectory.from_config(migration_config())
        self.assertEqual(scripts.get_heads(), ["0001_control_panel"])
        revision = scripts.get_revision("head")
        assert revision is not None
        self.assertIsNone(revision.down_revision)

    def test_initial_revision_renders_complete_postgres_ddl_without_a_database(self) -> None:
        output = StringIO()
        command.upgrade(migration_config(output_buffer=output), "head", sql=True)
        ddl = output.getvalue()
        created = set(re.findall(r"CREATE TABLE ([a-z_]+)\s*\(", ddl))
        self.assertEqual(created - {"alembic_version"}, set(Base.metadata.tables))
        self.assertEqual(len(created), 16)
        self.assertIn("CREATE TABLE bri_identity_sessions", ddl)
        self.assertIn("CREATE TABLE bri_identity_transactions", ddl)
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
            self.assertEqual(revision.down_revision, "0001_control_panel")
            content = Path(revision.path).read_text()
            compile(content, revision.path, "exec")
            self.assertEqual(ScriptDirectory.from_config(configuration).get_heads(), ["0002_test"])
