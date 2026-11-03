from __future__ import annotations

import fnmatch
import json
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from bri_catalog import (
    export_text,
    image_text,
    owned_sources,
    refresh,
    source_closure,
    watch_paths,
)
from bri_coolify import load_model, mapping, rendered_model
from bri_local import (
    LocalService,
    compose_command,
    ensure_deployment_environment,
    require_legacy_stack_stopped,
    runtime_values,
    start_units,
)
from ci_plan import NATIVE_BUILD_HELPER, plan

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Deployment:
    name: str
    compose: str
    watchers: tuple[str, ...]


def deployments() -> tuple[Deployment, ...]:
    document: object = json.loads((ROOT / "deploy/services.json").read_text())
    if not isinstance(document, dict) or not isinstance(document.get("services"), list):
        raise AssertionError("Invalid BRI deployment catalog")
    result: list[Deployment] = []
    for value in document["services"]:
        if not isinstance(value, dict):
            raise AssertionError("Invalid BRI unit")
        name, compose, watchers = value["name"], value["compose"], value["watch_paths"]
        if (
            not isinstance(name, str)
            or not isinstance(compose, str)
            or not isinstance(watchers, list)
        ):
            raise AssertionError("Invalid BRI deployment contract")
        if not all(isinstance(item, str) for item in watchers):
            raise AssertionError("Invalid BRI watcher")
        result.append(Deployment(name, compose, tuple(watchers)))
    return tuple(result)


def consumers(changed_path: str) -> frozenset[str]:
    return frozenset(
        unit.name
        for unit in deployments()
        if any(fnmatch.fnmatchcase(changed_path, pattern) for pattern in unit.watchers)
    )


class DeploymentIsolationContracts(unittest.TestCase):
    def test_api_start_does_not_require_old_data_transfer_receipts(self) -> None:
        api = LocalService(
            "control-panel-api", ROOT / "deploy/control-panel-api/docker-compose.yaml"
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("bri_local.STATE", Path(directory)),
            patch("bri_local.require_legacy_stack_stopped"),
            patch("bri_local.networks"),
            patch("bri_local.selected", return_value=(api,)),
            patch("bri_local.subprocess.run", return_value=subprocess.CompletedProcess([], 0)),
            patch("bri_local.compose") as compose,
        ):
            start_units(["control-panel-api"])
        self.assertEqual(compose.call_count, 1)
        self.assertEqual(compose.call_args.args[0], api)

    def test_required_environment_selects_generic_networks_and_preserves_volume_authority(
        self,
    ) -> None:
        for unit in deployments():
            with self.subTest(unit=unit.name):
                model = load_model(ROOT / unit.compose)
                for value in mapping(model["services"]).values():
                    environment = mapping(mapping(value)["environment"])
                    self.assertEqual(
                        environment["DEPLOYMENT_ENVIRONMENT"], "${DEPLOYMENT_ENVIRONMENT:?}"
                    )
                    self.assertNotIn("OTEL_ENVIRONMENT", environment)
                    if "OTEL_SERVICE_NAME" in environment:
                        self.assertEqual(environment["OTEL_ENDPOINT"], "${OTEL_ENDPOINT:-}")
                        self.assertEqual(environment["OTEL_BEARER_TOKEN"], "${OTEL_BEARER_TOKEN:-}")
                        self.assertEqual(
                            environment["OTEL_NAMESPACE"], "${OTEL_NAMESPACE:-briareus}"
                        )
                for value in mapping(model.get("networks", {})).values():
                    self.assertIn("${DEPLOYMENT_ENVIRONMENT:?}", str(mapping(value)["name"]))
                for value in mapping(model.get("volumes", {})).values():
                    self.assertIn("${DEPLOYMENT_ENVIRONMENT:?}", str(mapping(value)["name"]))

    def test_dependencies_share_one_resource_and_identity_stays_an_external_fixture(self) -> None:
        model = load_model(ROOT / "deploy/dependencies/docker-compose.yaml")
        self.assertEqual(
            set(mapping(model["services"])),
            {"postgres", "valkey", "chromium", "ghidra-engine", "ghidra-native"},
        )
        self.assertEqual(set(mapping(model["networks"])), {"bri-private"})
        all_services = {
            name for unit in deployments()
            for name in mapping(load_model(ROOT / unit.compose)["services"])
        }
        self.assertEqual(len(all_services), 16)
        self.assertNotIn("auth", all_services)
        self.assertFalse(any(name.startswith("zitadel") for name in all_services))
        fixture = load_model(ROOT / "tests/fixtures/zitadel/docker-compose.yaml")
        self.assertEqual(set(mapping(fixture["networks"])), {"identity-private"})
        identity_network = mapping(mapping(fixture["networks"])["identity-private"])
        self.assertFalse(identity_network.get("internal", False))
        ingress = mapping(mapping(fixture["services"])["zitadel-ingress"])
        self.assertEqual(ingress["ports"], ["127.0.0.1:18081:18081"])
        self.assertEqual(ingress["networks"], ["identity-private"])

    def test_local_projects_have_distinct_lifecycles_and_refuse_live_legacy_writers(self) -> None:
        api = LocalService(
            "control-panel-api", ROOT / "deploy/control-panel-api/docker-compose.yaml"
        )
        dependency = LocalService("dependencies", ROOT / "deploy/dependencies/docker-compose.yaml")
        with patch("bri_local.deployment_environment", return_value="development"):
            self.assertIn("briareus-v1-development-control-panel-api", compose_command(api))
            self.assertIn("briareus-v1-development-dependencies", compose_command(dependency))
        with (
            patch("bri_local.deployment_environment", return_value="production"),
            self.assertRaisesRegex(ValueError, "preserves development volumes"),
        ):
            compose_command(dependency)
        with (
            patch("bri_local.subprocess.check_output", return_value="old-active-id\n"),
            self.assertRaisesRegex(ValueError, "Stop the old bri-v1-local stack"),
        ):
            require_legacy_stack_stopped()
        with patch("bri_local.subprocess.check_output", return_value=""):
            require_legacy_stack_stopped()

    def test_coolify_inputs_stay_synchronized_without_claiming_destination_ownership(self) -> None:
        for unit in deployments():
            generic_path = ROOT / unit.compose
            coolify_path = generic_path.with_name("docker-compose.coolify.yaml")
            with self.subTest(unit=unit.name):
                self.assertEqual(coolify_path.read_text(), rendered_model(generic_path))
                model = load_model(coolify_path)
                self.assertNotIn("bri-private", mapping(model["networks"]))
                generic = load_model(generic_path)
                volumes = mapping(model.get("volumes", {}))
                original_volumes = mapping(generic.get("volumes", {}))
                self.assertEqual(set(volumes), set(original_volumes))
                for name, value in original_volumes.items():
                    expected = dict(mapping(value))
                    if name in {"workspace", "browser-profile", "browser-transfers"}:
                        expected["external"] = True
                        expected["name"] = str(expected["name"]).replace(
                            "bri-v1-", "briareus-v1-", 1
                        )
                    self.assertEqual(mapping(volumes[name]), expected)
                for name, value in mapping(model["services"]).items():
                    service = mapping(value)
                    self.assertNotIn("ports", service)
                    original = mapping(mapping(generic["services"])[name])
                    for key in ("volumes", "healthcheck", "restart"):
                        self.assertEqual(service.get(key), original.get(key))
                    environment = mapping(service["environment"])
                    for key, original_value in mapping(original["environment"]).items():
                        if key.endswith("_FILE") or key in {
                            "MCP_PUBLIC_BASE_URL", "CONTROL_PANEL_PUBLIC_BASE_URL"
                        }:
                            continue
                        self.assertEqual(environment[key], original_value)

    def test_local_configuration_migration_preserves_secret_values_and_is_repeatable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.env"
            path.write_text(
                "# retained\nCONTROL_PANEL_SESSION_SECRET=unchanged\n"
                "OTLP_ENDPOINT=https://collector.example.test\nOTLP_BEARER_TOKEN=keep=exact\n"
            )
            ensure_deployment_environment(path)
            first = path.read_bytes()
            ensure_deployment_environment(path)
            self.assertEqual(path.read_bytes(), first)
            values = runtime_values(path)
            self.assertEqual(values["CONTROL_PANEL_SESSION_SECRET"], "unchanged")
            self.assertEqual(values["OTEL_BEARER_TOKEN"], "keep=exact")
            self.assertEqual(values["OTEL_ENDPOINT"], "https://collector.example.test")
            self.assertEqual(values["DEPLOYMENT_ENVIRONMENT"], "development")
            self.assertEqual(values["OTEL_NAMESPACE"], "briareus")
            self.assertNotIn("OTLP_BEARER_TOKEN", values)
            self.assertTrue(path.read_text().startswith("# retained\n"))

    def test_conflicting_telemetry_aliases_do_not_rewrite_local_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.env"
            path.write_text("OTLP_BEARER_TOKEN=one\nOTEL_BEARER_TOKEN=another\n")
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                ensure_deployment_environment(path)
            self.assertEqual(path.read_bytes(), before)

    def test_legacy_local_environment_migrates_but_invalid_canonical_value_is_rejected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.env"
            path.write_text("OTEL_ENVIRONMENT=local\n")
            ensure_deployment_environment(path)
            self.assertEqual(runtime_values(path)["DEPLOYMENT_ENVIRONMENT"], "development")
            path.write_text("DEPLOYMENT_ENVIRONMENT=local\n")
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "Invalid DEPLOYMENT_ENVIRONMENT"):
                ensure_deployment_environment(path)
            self.assertEqual(path.read_bytes(), before)

    def test_ui_and_application_changes_do_not_redeploy_stable_dependencies(self) -> None:
        self.assertEqual(consumers("control-panel-ui/src/app/App.vue"), {"control-panel-ui"})
        self.assertEqual(consumers("src/modules/web/browser.py"), {"web"})
        self.assertEqual(consumers("src/browser_runtime/process.py"), {"dependencies"})
        self.assertNotIn("dependencies", consumers("src/modules/web/browser.py"))
        self.assertEqual(consumers("src/control_panel_api/oauth_host.py"), {"control-panel-api"})

    def test_owner_globs_select_new_files_without_redeploying_unrelated_resources(self) -> None:
        examples = {
            "control-panel-ui/src/features/new-view.vue": {"control-panel-ui"},
            "src/control_panel_api/new_feature/handler.py": {"control-panel-api"},
            "src/auth_service/new_policy.py": {"control-panel-api"},
            "src/modules/web/new_browser_action.py": {"web"},
            "src/modules/files/new_tools.py": {"files"},
            "src/browser_runtime/new_lifecycle.py": {"dependencies"},
            "src/modules/coolify/new_client_feature.py": {"observability"},
            "deploy/control-panel-api/README.md": {"control-panel-api"},
        }
        for path, expected in examples.items():
            with self.subTest(path=path):
                self.assertEqual(consumers(path), expected)

    def test_pasteable_coolify_watch_export_matches_the_authoritative_catalog(self) -> None:
        document = json.loads((ROOT / "deploy/services.json").read_text())
        refresh(document, check=True, images=True)
        self.assertEqual(
            (ROOT / "deploy/watch-paths.txt").read_text(encoding="utf-8"), export_text(document)
        )
        exported = export_text(document)
        self.assertEqual(exported.count("Branch: v1\n"), 12)
        self.assertEqual(exported.count("Compose Location: /docker-compose.coolify.yaml\n"), 12)

    def test_new_owner_files_and_shared_imports_require_copy_and_catalog_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src"
            (source / "common").mkdir(parents=True)
            (source / "common/__init__.py").write_text("")
            (source / "common/asgi.py").write_text("")
            (source / "widget").mkdir()
            (source / "widget/__init__.py").write_text("")
            (source / "widget/runtime.py").write_text("")
            deployment = root / "deploy/widget"
            deployment.mkdir(parents=True)
            (deployment / "docker-compose.yaml").write_text("services: {}\n")
            dockerfile = deployment / "Dockerfile"
            dockerfile.write_text("FROM scratch\nENV ASGI_APP=widget.runtime:app\n")
            service: dict[str, object] = {
                "name": "widget", "compose": "deploy/widget/docker-compose.yaml",
                "dockerfile": "deploy/widget/Dockerfile", "source_owners": ["src/widget"],
            }
            document: dict[str, object] = {"services": [service]}
            with patch("bri_catalog.ROOT", root), patch("bri_catalog.SOURCE", source):
                dockerfile.write_text(image_text(dockerfile, owned_sources(("src/widget",))))
                service["watch_paths"] = list(watch_paths(service))
                refresh(document, check=True, images=True)
                (source / "widget/new_feature.py").write_text("")
                with self.assertRaisesRegex(ValueError, "deploy/widget/Dockerfile"):
                    refresh(document, check=True, images=True)
                refresh(document, check=False, images=True)
                (source / "common/new_contract.py").write_text("value = 1\n")
                (source / "widget/new_feature.py").write_text(
                    "from common.new_contract import value\n"
                )
                with self.assertRaisesRegex(ValueError, "watch paths: widget"):
                    refresh(document, check=True, images=True)

    def test_shared_identity_transport_only_selects_actual_identity_consumers(self) -> None:
        self.assertEqual(
            consumers("src/common/identity_provider.py"),
            {"control-panel-api"},
        )
        self.assertTrue(
            {"web", "dependencies"}.issubset(consumers("src/common/browser_extensions.py"))
        )
        self.assertFalse(
            {"files", "github", "gitlab", "terminal"}
            & consumers("src/common/browser_extensions.py")
        )

    def test_every_imported_local_source_is_watched_by_its_owning_deployment(self) -> None:
        owners = {
            "gateway": "gateway",
            "control-panel-api": "control_panel_api",
            "dependencies": "browser_runtime",
            "web": "modules/web",
            "files": "modules/files",
            "github": "modules/github",
            "gitlab": "modules/gitlab",
            "terminal": "modules/terminal",
            "analysis": "modules/analysis",
            "ghidra": "modules/ghidra",
            "observability": "modules/observability",
        }
        for unit in deployments():
            if unit.name in owners:
                with self.subTest(unit=unit.name):
                    closure = source_closure(ROOT / "src" / owners[unit.name])
                    self.assertFalse({
                        path for path in closure
                        if not any(fnmatch.fnmatchcase(path, pattern) for pattern in unit.watchers)
                    })
                    self.assertNotIn("src/common/**", unit.watchers)
                    if unit.name == "control-panel-api":
                        template = "src/control_panel_api/infrastructure/alembic/script.py.mako"
                        self.assertTrue(any(
                            fnmatch.fnmatchcase(template, pattern) for pattern in unit.watchers
                        ))
                        image = (ROOT / "deploy/control-panel-api/Dockerfile").read_text()
                        self.assertIn(f"COPY {template} /app/{template}", image)
            self.assertTrue((ROOT / unit.compose).is_file())
            self.assertTrue(
                any(fnmatch.fnmatchcase(unit.compose, pattern) for pattern in unit.watchers)
            )

    def test_targeted_ci_keeps_renamed_owners_separate(self) -> None:
        for owner, path in (
            ("gateway", "src/gateway/server.py"),
            ("control-panel-api", "src/control_panel_api/application/identity.py"),
            ("chromium", "src/browser_runtime/process.py"),
        ):
            with self.subTest(owner=owner):
                result = plan([path])
                self.assertFalse(result["full"])
                self.assertEqual(result["areas"], [owner])
        result = plan(["deploy/hands/web/docker-compose.yaml"])
        self.assertTrue(result["compose"])
        self.assertFalse(result["full"])

    def test_ci_selects_contracts_from_changed_owners_and_test_files(self) -> None:
        native = plan([NATIVE_BUILD_HELPER])
        self.assertEqual(native["areas"], ["ghidra-build"])
        self.assertEqual(native["mypy_paths"], [NATIVE_BUILD_HELPER])
        self.assertEqual(native["ruff_paths"], [NATIVE_BUILD_HELPER])
        full = plan(["uv.lock"])
        mypy_paths, ruff_paths = full["mypy_paths"], full["ruff_paths"]
        assert isinstance(mypy_paths, list)
        assert isinstance(ruff_paths, list)
        self.assertIn(NATIVE_BUILD_HELPER, mypy_paths)
        self.assertIn(NATIVE_BUILD_HELPER, ruff_paths)
        self.assertEqual(
            plan(["src/browser_runtime/process.py"])["contract_modules"],
            ["test_bri_browser_contracts"],
        )
        self.assertEqual(
            plan(["tests/test_bri_mcp_revocation.py"])["contract_modules"],
            ["test_bri_mcp_revocation"],
        )
        self.assertEqual(
            plan(["deploy/services.json"])["contract_modules"],
            ["test_bri_deployment_boundaries", "test_bri_coolify_packaging"],
        )
        self.assertEqual(plan(["control-panel-ui/src/app/App.vue"])["contract_modules"], [])

    def test_ci_full_and_shared_fixture_plans_name_every_existing_suite(self) -> None:
        expected = sorted(path.stem for path in (ROOT / "tests").glob("test_*.py"))
        self.assertTrue(expected)
        for paths in (["uv.lock"], ["tests/bri_mcp_support.py"], [".github/workflows/ci.yaml"]):
            with self.subTest(paths=paths):
                actual = plan(paths)["contract_modules"]
                self.assertIsInstance(actual, list)
                assert isinstance(actual, list)
                self.assertEqual(sorted(actual), expected)
