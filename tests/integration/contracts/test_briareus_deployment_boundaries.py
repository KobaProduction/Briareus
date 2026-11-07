from __future__ import annotations

import fnmatch
import json
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from briareus_catalog import (
    export_text,
    refresh,
    source_closure,
)
from briareus_local import (
    LocalService,
    compose_command,
    ensure_deployment_environment,
    preserve_local_configuration,
    require_legacy_stack_stopped,
    require_replaced_writers_stopped,
    runtime_values,
    start_units,
)
from ci_plan import plan

from scripts.briareus_coolify import load_model, mapping, rendered_model

ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "deploy/services.json").is_file()
)


@dataclass(frozen=True)
class Deployment:
    name: str
    compose: str
    watchers: tuple[str, ...]


def deployments() -> tuple[Deployment, ...]:
    document: object = json.loads((ROOT / "deploy/services.json").read_text())
    if not isinstance(document, dict) or not isinstance(document.get("services"), list):
        raise AssertionError("Invalid Briareus deployment catalog")
    result: list[Deployment] = []
    for value in document["services"]:
        if not isinstance(value, dict):
            raise AssertionError("Invalid Briareus unit")
        name, compose, watchers = value["name"], value["compose"], value["watch_paths"]
        if (
            not isinstance(name, str)
            or not isinstance(compose, str)
            or not isinstance(watchers, list)
        ):
            raise AssertionError("Invalid Briareus deployment contract")
        if not all(isinstance(item, str) for item in watchers):
            raise AssertionError("Invalid Briareus watcher")
        result.append(Deployment(name, compose, tuple(watchers)))
    return tuple(result)


def consumers(changed_path: str) -> frozenset[str]:
    return frozenset(
        unit.name
        for unit in deployments()
        if any(fnmatch.fnmatchcase(changed_path, pattern) for pattern in unit.watchers)
    )


class DeploymentIsolationContracts(unittest.TestCase):
    def setUp(self) -> None:
        configuration = patch("briareus_local.local_configuration", return_value={})
        configuration.start()
        self.addCleanup(configuration.stop)

    def test_private_local_aliases_preserve_credentials_volume_names_and_writer_guard(self) -> None:
        configuration = {
            "environment_aliases": {"PREVIOUS_ENGINE_TOKEN": "BRIAREUS_GHIDRA_ENGINE_TOKEN"},
            "volume_overrides": {"BRIAREUS_LOCAL_POSTGRES_VOLUME": "existing-postgres-data"},
            "previous_projects": ["previous-application-owner"],
        }
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime.env"
            runtime.write_text(
                "PREVIOUS_ENGINE_TOKEN=retain-exact-secret\nPOSTGRES_PASSWORD=keep\n"
            )
            with patch("briareus_local.local_configuration", return_value=configuration):
                preserve_local_configuration(runtime)
                first = runtime.read_bytes()
                preserve_local_configuration(runtime)
                self.assertEqual(first, runtime.read_bytes())
                values = runtime_values(runtime)
                self.assertEqual(values["BRIAREUS_GHIDRA_ENGINE_TOKEN"], "retain-exact-secret")
                self.assertEqual(values["BRIAREUS_LOCAL_POSTGRES_VOLUME"], "existing-postgres-data")
                self.assertEqual(values["POSTGRES_PASSWORD"], "keep")
                with patch(
                    "briareus_local.subprocess.check_output", return_value="writer-id"
                ) as inspect:
                    with self.assertRaisesRegex(ValueError, "previous-application-owner"):
                        require_legacy_stack_stopped()
                    self.assertIn(
                        "label=com.docker.compose.project=previous-application-owner",
                        inspect.call_args.args[0],
                    )

    def test_renamed_dependency_checks_only_the_previous_service_writer(self) -> None:
        configuration = {
            "replaced_services": {
                "dependencies": [{"project": "existing-dependencies", "service": "previous-mcp"}]
            }
        }
        with (
            patch("briareus_local.local_configuration", return_value=configuration),
            patch("briareus_local.subprocess.check_output", return_value="old-writer") as inspect,
        ):
            require_replaced_writers_stopped(["control-panel-api"])
            inspect.assert_not_called()
            with self.assertRaisesRegex(ValueError, "Stop the previous previous-mcp container"):
                require_replaced_writers_stopped(["dependencies"])
            self.assertIn(
                "label=com.docker.compose.project=existing-dependencies", inspect.call_args.args[0]
            )
            self.assertIn(
                "label=com.docker.compose.service=previous-mcp", inspect.call_args.args[0]
            )

    def test_api_start_does_not_require_old_data_transfer_receipts(self) -> None:
        api = LocalService(
            "control-panel-api", ROOT / "services/control-panel/api/docker-compose.yaml"
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("briareus_local.STATE", Path(directory)),
            patch("briareus_local.require_legacy_stack_stopped"),
            patch("briareus_local.networks"),
            patch("briareus_local.selected", return_value=(api,)),
            patch("briareus_local.subprocess.run", return_value=subprocess.CompletedProcess([], 0)),
            patch("briareus_local.compose") as compose,
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
        model = load_model(ROOT / "services/dependencies/docker-compose.yaml")
        self.assertEqual(
            set(mapping(model["services"])),
            {"postgres", "valkey", "chromium"},
        )
        adapter = load_model(ROOT / "services/hands/ghidra/docker-compose.yaml")
        environment = mapping(mapping(mapping(adapter["services"])["ghidra"])["environment"])
        self.assertEqual(environment["GHIDRA_MCP_URL"], "${GHIDRA_MCP_URL:?}")
        analysis = load_model(ROOT / "services/hands/analysis/docker-compose.yaml")
        upload = mapping(mapping(mapping(analysis["services"])["analysis"])["environment"])
        self.assertEqual(upload["GHIDRA_DIRECT_UPLOAD_URL"], "${GHIDRA_DIRECT_UPLOAD_URL:?}")
        self.assertEqual(set(mapping(model["networks"])), {"briareus-private"})
        all_services = {
            name
            for unit in deployments()
            for name in mapping(load_model(ROOT / unit.compose)["services"])
        }
        self.assertEqual(len(all_services), 13)
        self.assertEqual(len(deployments()), 11)
        self.assertIn("server", all_services)
        self.assertNotIn("files", all_services)
        self.assertNotIn("terminal", all_services)
        document = json.loads((ROOT / "deploy/services.json").read_text())
        server = next(unit for unit in document["services"] if unit["name"] == "server")
        self.assertEqual(server["source_owners"], ["services/hands/server/src/briareus_server"])
        from briareus_mcp_resources import MCP_SURFACE_PATHS

        self.assertEqual(MCP_SURFACE_PATHS["server"], "/server/mcp")
        self.assertNotIn("files", MCP_SURFACE_PATHS)
        self.assertNotIn("terminal", MCP_SURFACE_PATHS)
        self.assertNotIn("auth", all_services)
        self.assertFalse(any(name.startswith("zitadel") for name in all_services))
        fixture = load_model(ROOT / "tests/fixtures/zitadel/docker-compose.yaml")
        self.assertEqual(set(mapping(fixture["networks"])), {"identity-private"})
        identity_network = mapping(mapping(fixture["networks"])["identity-private"])
        self.assertFalse(identity_network.get("internal", False))
        ingress = mapping(mapping(fixture["services"])["zitadel-ingress"])
        self.assertEqual(ingress["ports"], ["127.0.0.1:18081:18081"])
        self.assertEqual(ingress["networks"], ["identity-private"])

    def test_dependencies_have_only_their_own_external_infrastructure_inputs(self) -> None:
        document = json.loads((ROOT / "deploy/services.json").read_text())
        dependency = next(unit for unit in document["services"] if unit["name"] == "dependencies")
        self.assertEqual(dependency["source_owners"], [])
        self.assertFalse(dependency.get("source_images", []))
        self.assertNotIn("dockerfile", dependency)
        self.assertEqual(dependency["watch_paths"], ["services/dependencies/**"])
        for owner in document["services"]:
            if owner["name"] == "dependencies":
                continue
            for pattern in owner["watch_paths"]:
                self.assertNotEqual(pattern, "services/dependencies/**")
        for path in (
            "shared/contracts/json-values/src/briareus_json_values/__init__.py",
            "shared/python/environment-models/src/briareus_environment_models/__init__.py",
            "shared/server/workspace-mount/src/briareus_server_mount/__init__.py",
            "services/hands/web/src/briareus_web/browser_control.py",
        ):
            self.assertNotIn("dependencies", consumers(path))
        dependency_dir = ROOT / "services/dependencies"
        services = mapping(load_model(dependency_dir / "docker-compose.yaml")["services"])
        for name, value in services.items():
            build = mapping(value).get("build")
            if build is None:
                continue
            build = mapping(build)
            context = (dependency_dir / str(build["context"])).resolve()
            self.assertTrue(context.is_relative_to(dependency_dir))
            recipe = (context / str(build["dockerfile"])).read_text()
            with self.subTest(image=name):
                self.assertNotIn("/app/src", recipe)
                self.assertNotIn("COPY shared/", recipe)
                self.assertNotIn("COPY services/", recipe)
                for line in recipe.splitlines():
                    if line.startswith("COPY ") and "--from=" not in line:
                        for source in line.split()[1:-1]:
                            self.assertFalse(source.startswith(("/", "../")), source)
                            self.assertTrue((context / source).is_file(), source)

    def test_narrow_policy_modules_select_only_their_semantic_consumers(self) -> None:
        expected = {
            "github": {"control-panel-api", "github"},
            "gitlab": {"control-panel-api", "gitlab"},
            "terminal": {"control-panel-api", "server"},
            "browser": {"control-panel-api", "web"},
        }
        for capability, owners in expected.items():
            path = f"shared/policies/{capability}/src/briareus_{capability}_policy/__init__.py"
            with self.subTest(capability=capability):
                self.assertEqual(consumers(path), owners)
                selected = plan([path])
                self.assertEqual(set(selected["areas"]), owners)
                self.assertNotIn("dependencies", selected["areas"])
        for unit in deployments():
            self.assertNotIn("shared/contracts/**", unit.watchers)
            self.assertNotIn("shared/policies/**", unit.watchers)
            self.assertNotIn("shared/python/**", unit.watchers)

    def test_server_browser_git_and_api_mount_the_same_canonical_workspace(self) -> None:
        expected = {"server", "web", "github", "gitlab", "control-panel-api", "analysis"}
        watched = consumers("shared/server/workspace-mount/src/briareus_server_mount/__init__.py")
        self.assertEqual(watched, expected)
        volumes = set()
        for unit in deployments():
            if unit.name not in expected:
                continue
            model = load_model(ROOT / unit.compose)
            service = mapping(mapping(model["services"])[unit.name])
            environment = mapping(service["environment"])
            with self.subTest(owner=unit.name):
                self.assertEqual(
                    environment["SERVER_MOUNT_PATH"], "${SERVER_MOUNT_PATH:-/workspace}"
                )
                self.assertNotIn("FILE_WORKSPACE_ROOT", environment)
                self.assertNotIn("TERMINAL_WORKSPACE_ROOT", environment)
                self.assertIn("workspace:${SERVER_MOUNT_PATH:-/workspace}", service["volumes"])
                volumes.add(mapping(mapping(model["volumes"])["workspace"])["name"])
        self.assertEqual(volumes, {"briareus-v1-${DEPLOYMENT_ENVIRONMENT:?}-workspace"})

    def test_local_projects_have_distinct_lifecycles_and_refuse_live_legacy_writers(self) -> None:
        api = LocalService(
            "control-panel-api", ROOT / "services/control-panel/api/docker-compose.yaml"
        )
        dependency = LocalService(
            "dependencies", ROOT / "services/dependencies/docker-compose.yaml"
        )
        with patch("briareus_local.deployment_environment", return_value="development"):
            self.assertIn("briareus-v1-development-control-panel-api", compose_command(api))
            self.assertIn("briareus-v1-development-dependencies", compose_command(dependency))
        with (
            patch("briareus_local.deployment_environment", return_value="production"),
            self.assertRaisesRegex(ValueError, "preserves development volumes"),
        ):
            compose_command(dependency)
        with (
            patch("briareus_local.subprocess.check_output", return_value="old-active-id\n"),
            self.assertRaisesRegex(ValueError, "Stop the old briareus-v1-local stack"),
        ):
            require_legacy_stack_stopped()
        with patch("briareus_local.subprocess.check_output", return_value=""):
            require_legacy_stack_stopped()

    def test_coolify_inputs_stay_synchronized_without_claiming_destination_ownership(self) -> None:
        for unit in deployments():
            generic_path = ROOT / unit.compose
            coolify_path = generic_path.with_name("docker-compose.coolify.yaml")
            with self.subTest(unit=unit.name):
                self.assertEqual(coolify_path.read_text(), rendered_model(generic_path))
                model = load_model(coolify_path)
                self.assertNotIn("briareus-private", mapping(model["networks"]))
                generic = load_model(generic_path)
                volumes = mapping(model.get("volumes", {}))
                original_volumes = mapping(generic.get("volumes", {}))
                self.assertEqual(set(volumes), set(original_volumes))
                for name, value in original_volumes.items():
                    expected = dict(mapping(value))
                    expected["name"] = str(expected["name"]).replace(
                        "${DEPLOYMENT_ENVIRONMENT:?}", "${DEPLOYMENT_ENVIRONMENT}"
                    )
                    if name in {"workspace", "browser-profile", "browser-transfers"}:
                        expected["external"] = True
                    self.assertEqual(mapping(volumes[name]), expected)
                for name, value in mapping(model["services"]).items():
                    service = mapping(value)
                    self.assertNotIn("ports", service)
                    original = mapping(mapping(generic["services"])[name])
                    for key in ("healthcheck", "restart"):
                        self.assertEqual(service.get(key), original.get(key))
                    environment = mapping(service["environment"])
                    for key, original_value in mapping(original["environment"]).items():
                        if key.endswith("_FILE") or key in {
                            "MCP_PUBLIC_BASE_URL",
                            "CONTROL_PANEL_PUBLIC_BASE_URL",
                            "SERVER_MOUNT_PATH",
                            "BROWSER_DOWNLOADS_PATH",
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
        self.assertEqual(
            consumers("services/control-panel/ui/src/app/App.vue"), {"control-panel-ui"}
        )
        self.assertEqual(consumers("services/hands/web/src/briareus_web/browser.py"), {"web"})
        self.assertEqual(
            consumers("services/dependencies/chromium/chromium-launch.sh"),
            {"dependencies"},
        )
        self.assertNotIn(
            "dependencies", consumers("services/hands/web/src/briareus_web/browser.py")
        )
        self.assertEqual(
            consumers("services/control-panel/api/src/control_panel_api/application/identity.py"),
            {"control-panel-api"},
        )

    def test_owner_globs_select_new_files_without_redeploying_unrelated_resources(self) -> None:
        examples = {
            "services/control-panel/ui/src/features/new-view.vue": {"control-panel-ui"},
            "services/control-panel/api/src/control_panel_api/new_feature/handler.py": {
                "control-panel-api"
            },
            "services/control-panel/api/src/control_panel_api/new_policy.py": {"control-panel-api"},
            "services/hands/web/src/briareus_web/new_browser_action.py": {"web"},
            "services/hands/server/src/briareus_server/files/new_tools.py": {"server"},
            "services/hands/server/src/briareus_server/terminal/new_tools.py": {"server"},
            "services/dependencies/chromium/new-infrastructure.conf": {"dependencies"},
            "services/hands/observability/src/briareus_coolify/new_client_feature.py": {
                "observability"
            },
            "services/control-panel/api/README.md": {"control-panel-api"},
        }
        for path, expected in examples.items():
            with self.subTest(path=path):
                self.assertEqual(consumers(path), expected)

    def test_operator_handout_is_private_and_all_watches_are_directory_globs(self) -> None:
        from briareus_catalog import EXPORT

        document = json.loads((ROOT / "deploy/services.json").read_text())
        refresh(document, check=True, images=True)
        exported = export_text(document)
        self.assertTrue(EXPORT.is_relative_to(ROOT / ".local"))
        self.assertFalse((ROOT / "deploy/watch-paths.txt").exists())
        self.assertEqual(document["services"][0]["name"], "control-panel-ui")
        self.assertLess(exported.index("[control-panel-ui]"), exported.index("[control-panel-api]"))
        self.assertEqual(exported.count("Compose Location: /docker-compose.coolify.yaml\n"), 11)
        for unit in deployments():
            for pattern in unit.watchers:
                self.assertTrue(pattern.endswith("/**"), pattern)
                self.assertNotIn("*", pattern[:-3])
                self.assertTrue((ROOT / pattern[:-3]).is_dir(), pattern)
                self.assertNotEqual(pattern, "shared/**")

    def test_package_copy_automatically_includes_new_files_and_new_shared_imports_refresh_watches(
        self,
    ) -> None:
        import briareus_catalog as catalog

        def clear_caches() -> None:
            for function in (
                catalog.source_roots,
                catalog.packages,
                catalog.imports,
                catalog.source_packages,
            ):
                function.cache_clear()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owner = root / "services/widget/src/widget"
            owner.mkdir(parents=True)
            (owner / "__init__.py").write_text("")
            (owner / "runtime.py").write_text("")
            shared = root / "shared/contracts/feature/src/briareus_feature"
            shared.mkdir(parents=True)
            (shared / "__init__.py").write_text("")
            (shared / "contract.py").write_text("value = 1\n")
            deployment = root / "services/widget"
            (deployment / "docker-compose.yaml").write_text("services: {}\n")
            dockerfile = deployment / "Dockerfile"
            dockerfile.write_text("FROM scratch\nENV ASGI_APP=widget.runtime:app\n")
            service: dict[str, object] = {
                "name": "widget",
                "compose": "services/widget/docker-compose.yaml",
                "dockerfile": "services/widget/Dockerfile",
                "source_owners": ["services/widget/src/widget"],
            }
            document: dict[str, object] = {"services": [service]}
            clear_caches()
            try:
                with patch("briareus_catalog.ROOT", root):
                    refresh(document, check=False, images=True)
                    original = dockerfile.read_text()
                    (owner / "new_feature.py").write_text("")
                    clear_caches()
                    refresh(document, check=True, images=True)
                    self.assertEqual(dockerfile.read_text(), original)
                    (owner / "new_feature.py").write_text(
                        "from briareus_feature.contract import value\n"
                    )
                    clear_caches()
                    with self.assertRaisesRegex(ValueError, "watch paths: widget"):
                        refresh(document, check=True, images=True)
                    refresh(document, check=False, images=True)
                    self.assertIn("shared/contracts/feature/**", service["watch_paths"])
                    self.assertIn(
                        "COPY shared/contracts/feature/src/briareus_feature "
                        "/app/src/briareus_feature",
                        dockerfile.read_text(),
                    )
                    (owner / "broken_import.py").write_text("from .missing_module import value\n")
                    clear_caches()
                    with self.assertRaisesRegex(ValueError, "Unresolved first-party import"):
                        refresh(document, check=True, images=True)
            finally:
                clear_caches()

    def test_shared_identity_transport_only_selects_actual_identity_consumers(self) -> None:
        self.assertEqual(
            consumers("shared/identity/token-verification/src/briareus_zitadel_tokens/verifier.py"),
            {"control-panel-api", "gateway"},
        )
        self.assertEqual(
            consumers("services/hands/web/src/briareus_web/browser_extensions.py"),
            {"web"},
        )

    def test_every_imported_local_source_and_package_resource_is_owned_and_watched(self) -> None:
        document = json.loads((ROOT / "deploy/services.json").read_text())
        for service in document["services"]:
            watchers = service["watch_paths"]
            for owner in service["source_owners"]:
                for path in source_closure(ROOT / owner):
                    self.assertTrue(
                        any(fnmatch.fnmatchcase(path, pattern) for pattern in watchers), path
                    )
            self.assertTrue(
                any(fnmatch.fnmatchcase(service["compose"], pattern) for pattern in watchers)
            )
        template = (
            ROOT
            / "services/control-panel/api/src/control_panel_api"
            / "infrastructure/alembic/script.py.mako"
        )
        self.assertTrue(template.is_file())
        image = (ROOT / "services/control-panel/api/Dockerfile").read_text()
        self.assertIn(
            "COPY services/control-panel/api/src/control_panel_api /app/src/control_panel_api",
            image,
        )

    def test_targeted_ci_keeps_renamed_owners_separate(self) -> None:
        for owner, path in (
            ("gateway", "services/gateway/src/gateway/server.py"),
            (
                "control-panel-api",
                "services/control-panel/api/src/control_panel_api/application/identity.py",
            ),
            ("server", "services/hands/server/src/briareus_server/runtime.py"),
            ("web", "services/hands/web/src/briareus_web/browser_control.py"),
        ):
            with self.subTest(owner=owner):
                result = plan([path])
                self.assertFalse(result["full"])
                self.assertEqual(result["areas"], [owner])
        result = plan(["services/hands/web/docker-compose.yaml"])
        self.assertTrue(result["compose"])
        self.assertFalse(result["full"])

    def test_ci_selects_contracts_from_changed_owners_and_test_files(self) -> None:
        self.assertTrue(
            plan(["services/control-panel/api/tests/integration/postgres_migrations.py"])[
                "postgres"
            ]
        )
        self.assertFalse(plan(["services/control-panel/ui/src/app/App.vue"])["postgres"])
        full = plan(["uv.lock"])
        mypy_paths, ruff_paths = full["mypy_paths"], full["ruff_paths"]
        assert isinstance(mypy_paths, list)
        assert isinstance(ruff_paths, list)
        self.assertTrue(all((ROOT / path).is_dir() for path in mypy_paths))
        self.assertIn("services", ruff_paths)
        self.assertEqual(
            plan(["services/dependencies/chromium/Dockerfile"])["mypy_paths"],
            [],
        )
        self.assertEqual(
            plan(["services/control-panel/api/tests/test_briareus_panel_tokens.py"])[
                "contract_modules"
            ],
            ["test_briareus_panel_tokens"],
        )
        self.assertEqual(
            plan(["deploy/services.json"])["contract_modules"],
            ["test_briareus_deployment_boundaries", "test_briareus_coolify_packaging"],
        )
        self.assertEqual(
            plan(["services/control-panel/ui/src/app/App.vue"])["contract_modules"], []
        )

    def test_ci_shared_changes_select_disjoint_source_roots_without_test_fixtures(self) -> None:
        owner = "shared/identity/token-verification"
        result = plan([
            owner + "/src/briareus_zitadel_tokens/verifier.py",
            owner + "/tests/test_briareus_zitadel_tokens.py",
            owner + "/tests/zitadel_test_support.py",
            "shared/cache/src/briareus_cache/cache.py",
        ])
        paths = result["mypy_paths"]
        assert isinstance(paths, list)
        self.assertEqual(paths.count(owner + "/src"), 1)
        self.assertIn("shared/cache/src", paths)
        self.assertTrue(all((ROOT / path).is_dir() for path in paths))
        for path in paths:
            self.assertFalse(any(path.startswith(other + "/") for other in paths if path != other))
        self.assertIn("test_briareus_zitadel_tokens", result["contract_modules"])

    def test_ci_full_and_shared_fixture_plans_name_every_existing_suite(self) -> None:
        from ci_plan import all_contracts

        expected = list(all_contracts())
        self.assertTrue(expected)
        for paths in (
            ["uv.lock"],
            ["tests/support/briareus_support.py"],
            [".github/workflows/ci.yaml"],
        ):
            with self.subTest(paths=paths):
                self.assertEqual(sorted(plan(paths)["contract_modules"]), expected)
