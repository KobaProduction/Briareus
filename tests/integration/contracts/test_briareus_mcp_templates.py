from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from scripts.briareus_catalog import watch_paths
from scripts.briareus_coolify import ROOT, coolify_model, mapping, resolved_model


class McpDeploymentTemplateContracts(unittest.TestCase):
    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI acceptance runs on the host")
    def test_flattened_provider_keeps_required_inputs_and_owner_relative_build_paths(self) -> None:
        owner = ROOT / "services/hands/svc/github"
        model = coolify_model(resolved_model(owner / "docker-compose.yaml"))
        service = mapping(mapping(model["services"])["github"])
        environment = mapping(service["environment"])
        self.assertNotIn("name", model)
        self.assertNotIn("extends", service)
        self.assertEqual(environment["BRIAREUS_SERVICE_TOKEN"], "${BRIAREUS_SERVICE_TOKEN:?}")
        self.assertEqual(environment["VALKEY_PASSWORD"], "${VALKEY_PASSWORD:?}")
        self.assertEqual(environment["DEPLOYMENT_ENVIRONMENT"], "${DEPLOYMENT_ENVIRONMENT:?}")
        self.assertEqual(environment["SERVER_MOUNT_PATH"], "/workspace")
        self.assertEqual(mapping(service["build"])["context"], "../../../..")
        self.assertEqual(
            mapping(service["build"])["dockerfile"],
            "services/hands/svc/github/Dockerfile",
        )
        volumes = service["volumes"]
        self.assertIsInstance(volumes, list)
        self.assertEqual(mapping(cast(list[object], volumes)[0])["target"], "/workspace")
        self.assertEqual(mapping(service["healthcheck"])["retries"], 20)

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI acceptance runs on the host")
    def test_flattening_does_not_load_implicit_or_ambient_environment_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="briareus-compose-") as directory:
            owner = Path(directory)
            environment_file = owner / ".env"
            environment_file.write_text('UNTERMINATED="not-a-valid-env-file\n', encoding="utf-8")
            template = (ROOT / "deploy/templates/mcp-service.yaml").as_posix()
            compose = owner / "docker-compose.yaml"
            compose.write_text(
                "services:\n  provider:\n    extends:\n"
                f"      file: {template}\n      service: mcp-service\n"
                "    image: example.test/provider:test\n"
                "    environment:\n      TZ: UTC\n"
                "networks:\n  briareus-private:\n    external: true\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"COMPOSE_ENV_FILES": str(environment_file)}):
                model = resolved_model(compose)
        service = mapping(mapping(model["services"])["provider"])
        self.assertEqual(service["restart"], "unless-stopped")
        # Canonical Compose can use list form before Coolify materialization.
        environment = mapping(mapping(coolify_model(model)["services"])["provider"])["environment"]
        self.assertEqual(mapping(environment)["TZ"], "UTC")
        self.assertEqual(mapping(environment)["VALKEY_PASSWORD"], "${VALKEY_PASSWORD:?}")

    def test_template_watch_is_scoped_to_mcp_owners_not_dependencies(self) -> None:
        provider = {
            "name": "signoz",
            "compose": "services/hands/observability/signoz/docker-compose.yaml",
            "source_owners": [],
        }
        dependencies = {
            "name": "dependencies",
            "compose": "services/dependencies/docker-compose.yaml",
            "source_owners": [],
        }
        self.assertIn("deploy/templates/**", watch_paths(provider))
        self.assertNotIn("deploy/templates/**", watch_paths(dependencies))
