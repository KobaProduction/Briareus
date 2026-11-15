"""Contract for Docker-free Compose checking and optional Docker conformance."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import validate_compose
from scripts.briareus_coolify import coolify_model, rendered_model, yaml
from scripts.compose_portable import resolve
from scripts.quality_gate import database_coverage, selected_test_backend


class PortableComposeContracts(unittest.TestCase):
    def test_native_resolution_preserves_all_current_coolify_models(self) -> None:
        files = sorted(Path("services").glob("**/docker-compose.coolify.yaml"))
        self.assertGreaterEqual(len(files), 15)
        for target in files:
            with self.subTest(path=str(target)):
                generic = target.with_name("docker-compose.yaml")
                self.assertEqual(
                    coolify_model(resolve(generic)), yaml.safe_load(target.read_text())
                )
                self.assertEqual(rendered_model(generic), target.read_text())

    def test_portable_compose_validation_never_calls_docker(self) -> None:
        with (
            patch(
                "scripts.validate_compose.subprocess.run", side_effect=AssertionError("Docker used")
            ),
            patch("sys.argv", ["validate_compose.py"]),
        ):
            validate_compose.main()

    def test_explicit_docker_validator_is_still_supported(self) -> None:
        with (
            patch(
                "scripts.validate_compose.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0),
            ) as invoked,
            patch("sys.argv", ["validate_compose.py", "--docker"]),
        ):
            validate_compose.main()
        self.assertEqual(invoked.call_count, len(validate_compose.compose_paths()))
        self.assertTrue(
            all(call.args[0][:2] == ["docker", "compose"] for call in invoked.call_args_list)
        )

    def test_gate_credits_only_selected_database_backend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "artifacts" / "briareus-alembic-postgres-acceptance.json"
            report.parent.mkdir()
            report.write_text(
                '{"passed":true,"database_backend":"sqlite",'
                '"sqlite_migration_coverage":true,"postgres_coverage":false}'
            )
            with patch("scripts.quality_gate.ROOT", Path(directory)):
                self.assertTrue(database_coverage("sqlite"))
                with self.assertRaisesRegex(ValueError, "selected backend"):
                    database_coverage("postgresql")
            report.write_text(
                '{"passed":true,"database_backend":"both",'
                '"sqlite_migration_coverage":true,"postgres_coverage":false}'
            )
            with patch("scripts.quality_gate.ROOT", Path(directory)):
                self.assertFalse(database_coverage("both"))
            report.write_text(
                '{"passed":true,"database_backend":"both",'
                '"sqlite_migration_coverage":true,"postgres_coverage":true}'
            )
            with patch("scripts.quality_gate.ROOT", Path(directory)):
                self.assertTrue(database_coverage("both"))

    def test_sqlite_is_default_and_other_backends_are_explicit(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(selected_test_backend(), "sqlite")
        for backend in ("sqlite", "postgresql", "both"):
            with patch.dict("os.environ", {"BRIAREUS_TEST_DATABASE_BACKEND": backend}):
                self.assertEqual(selected_test_backend(), backend)

    def test_missing_or_escaped_template_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "docker-compose.yaml"
            path.write_text(
                "services:\n  app:\n    extends:\n      file: ../outside.yaml\n      service: x\n"
            )
            with self.assertRaises(ValueError):
                resolve(path)

    def test_unsupported_nested_template_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("scripts.compose_portable.ROOT", root):
                (root / "base.yaml").write_text(
                    "services:\n  base:\n    extends:\n"
                    "      file: other.yaml\n      service: nested\n"
                )
                path = root / "docker-compose.yaml"
                path.write_text(
                    "services:\n  child:\n    extends:\n"
                    "      file: base.yaml\n      service: base\n"
                )
                with self.assertRaisesRegex(ValueError, "Nested Compose extends"):
                    resolve(path)
