from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from briareus_dockerfiles import dockerignore, image_paths, standalone_dockerfile
from briareus_local import ensure_dependency_environment, runtime_values
from deployment_models import Mount, service_mounts
from deployment_models import generic_model as load_model

from scripts.briareus_coolify import coolify_model, mapping

ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "deploy/services.json").is_file()
)


class CoolifyPackagingContracts(unittest.TestCase):
    def test_coolify_volume_names_use_supported_variables_and_environment_remains_required(
        self,
    ) -> None:
        document = json.loads((ROOT / "deploy/services.json").read_text())
        for unit in document["services"]:
            path = (ROOT / unit["compose"]).with_name("docker-compose.coolify.yaml")
            model = load_model(path)
            for value in mapping(model.get("volumes", {})).values():
                name = str(mapping(value)["name"])
                self.assertIn("${DEPLOYMENT_ENVIRONMENT}", name)
                self.assertRegex(name, r"^briareus-v1-\$\{DEPLOYMENT_ENVIRONMENT\}-[a-z0-9-]+$")
            for value in mapping(model["services"]).values():
                environment = mapping(mapping(value)["environment"])
                self.assertEqual(
                    environment["DEPLOYMENT_ENVIRONMENT"], "${DEPLOYMENT_ENVIRONMENT:?}"
                )

    def test_coolify_workspace_uses_literal_target_and_matching_consumer_paths(self) -> None:
        document = json.loads((ROOT / "deploy/services.json").read_text())
        consumers: set[str] = set()
        for unit in document["services"]:
            generic = load_model(ROOT / unit["compose"])
            deployed = load_model((ROOT / unit["compose"]).with_name("docker-compose.coolify.yaml"))
            for name, value in mapping(deployed["services"]).items():
                service = mapping(value)
                original = mapping(mapping(generic["services"])[name])
                expected_mounts = tuple(
                    Mount(mount.source, "/workspace", mount.mount_type, mount.read_only)
                    if mount.source == "workspace"
                    and mount.target == "${SERVER_MOUNT_PATH:-/workspace}"
                    else mount
                    for mount in service_mounts(original)
                )
                self.assertEqual(service_mounts(service), expected_mounts)
                if Mount("workspace", "/workspace") in expected_mounts:
                    consumers.add(name)
                    environment = mapping(service["environment"])
                    self.assertEqual(environment["SERVER_MOUNT_PATH"], "/workspace")
                    if "BROWSER_DOWNLOADS_PATH" in environment:
                        self.assertEqual(
                            environment["BROWSER_DOWNLOADS_PATH"], "/workspace/browser/downloads"
                        )
        self.assertEqual(
            consumers,
            {
                "chromium",
                "control-panel-api",
                "github-mcp-hand",
                "gitlab-mcp-hand",
                "server-mcp-hand",
                "playwright-mcp-hand",
                "radare2-mcp-hand",
                "analysis-g-mcp-hand",
                "serena-mcp-hand",
            },
        )

    def test_coolify_path_normalization_does_not_mutate_generic_compose(self) -> None:
        generic = load_model(ROOT / "services/dependencies/docker-compose.yaml")
        before = json.dumps(generic, sort_keys=True)
        coolify_model(generic)
        self.assertEqual(json.dumps(generic, sort_keys=True), before)
        chromium = mapping(mapping(generic["services"])["chromium"])
        mounts = chromium["volumes"]
        assert isinstance(mounts, list)
        self.assertIn("workspace:${SERVER_MOUNT_PATH:-/workspace}", mounts)
        self.assertEqual(
            mapping(chromium["environment"])["BROWSER_DOWNLOADS_PATH"],
            "${SERVER_MOUNT_PATH:-/workspace}/browser/downloads",
        )

    def test_each_python_image_has_the_current_self_contained_dependency_recipe(self) -> None:
        paths = image_paths()
        document = json.loads((ROOT / "deploy/services.json").read_text())
        expected = sum(bool(service.get("dockerfile")) for service in document["services"])
        expected += sum(len(service.get("source_images", [])) for service in document["services"])
        self.assertEqual(len(paths), expected)
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                source = path.read_text()
                owner = path.parent.relative_to(ROOT).as_posix()
                self.assertEqual(source, standalone_dockerfile(source, owner))
                self.assertIn(f"COPY {owner}/pyproject.toml {owner}/uv.lock ./", source)
                self.assertNotIn("COPY pyproject.toml uv.lock", source)
                self.assertNotIn("RUNTIME_BASE", source)
                self.assertEqual(
                    path.with_name(path.name + ".dockerignore").read_text(),
                    dockerignore(source, owner),
                )
                for copied in source.splitlines():
                    if copied.startswith("COPY ") and "/src/" in copied:
                        self.assertTrue((ROOT / copied.split()[1]).is_dir(), copied)

    def test_coolify_has_one_public_route_and_no_host_checkout_or_secret_files(self) -> None:
        document = json.loads((ROOT / "deploy/services.json").read_text())
        routes: list[tuple[str, str]] = []
        for unit in document["services"]:
            path = (ROOT / unit["compose"]).with_name("docker-compose.coolify.yaml")
            model = load_model(path)
            with self.subTest(resource=unit["name"]):
                self.assertNotIn("secrets", model)
                for name, value in mapping(model["services"]).items():
                    service = mapping(value)
                    self.assertNotIn("ports", service)
                    self.assertNotIn("secrets", service)
                    environment = mapping(service["environment"])
                    self.assertFalse(any(key.endswith("_FILE") for key in environment))
                    routes.extend(
                        (name, key) for key in environment if key.startswith("SERVICE_URL_")
                    )
                    build = service.get("build")
                    if isinstance(build, dict):
                        self.assertNotIn("BRIAREUS_RUNTIME_BASE", mapping(build.get("args", {})))
                        self.assertNotIn("BRIAREUS_GHIDRA_SOURCE_DIR", str(build))
                        self.assertNotIn("BRIAREUS_SOURCE_DIR", str(build))
        self.assertEqual(routes, [("gateway", "SERVICE_URL_GATEWAY_8000")])

    def test_secret_and_origin_consumers_use_explicit_coolify_inputs(self) -> None:
        api = mapping(
            mapping(
                load_model(ROOT / "services/control-panel/api/docker-compose.coolify.yaml")[
                    "services"
                ]
            )["control-panel-api"]
        )
        environment = mapping(api["environment"])
        for key in (
            "BRIAREUS_SERVICE_TOKEN",
            "OIDC_ISSUER_URL",
            "OIDC_AUDIENCE",
            "OIDC_PANEL_CLIENT_ID",
        ):
            self.assertEqual(environment[key], "${" + key + ":?}")
        self.assertFalse(any(key.startswith("MCP_OAUTH_") for key in environment))
        self.assertNotIn("ZITADEL_CLIENT_SECRET", environment)
        self.assertNotIn("CONTROL_PANEL_SESSION_SECRET", environment)
        self.assertEqual(environment["CONTROL_PANEL_PUBLIC_BASE_URL"], "${MCP_PUBLIC_BASE_URL:?}")
        gateway = mapping(
            mapping(load_model(ROOT / "services/gateway/docker-compose.coolify.yaml")["services"])[
                "gateway"
            ]
        )
        self.assertEqual(
            mapping(gateway["environment"])["MCP_PUBLIC_BASE_URL"], "${SERVICE_URL_GATEWAY}"
        )

    def test_cross_resource_volumes_are_external_and_share_one_fresh_name(self) -> None:
        document = json.loads((ROOT / "deploy/services.json").read_text())
        shared: dict[str, set[str]] = {}
        for unit in document["services"]:
            path = (ROOT / unit["compose"]).with_name("docker-compose.coolify.yaml")
            for key, value in mapping(load_model(path).get("volumes", {})).items():
                volume = mapping(value)
                if key in {"workspace", "browser-profile", "browser-transfers"}:
                    self.assertIs(volume.get("external"), True)
                    name = str(volume["name"])
                    self.assertIn("${DEPLOYMENT_ENVIRONMENT}", name)
                    self.assertTrue(name.startswith("briareus-v1-"))
                    self.assertNotIn("local", name)
                    shared.setdefault(key, set()).add(name)
                else:
                    self.assertFalse(volume.get("external", False))
        self.assertEqual(set(shared), {"workspace", "browser-profile", "browser-transfers"})
        self.assertTrue(all(len(names) == 1 for names in shared.values()))

    def test_local_configuration_is_repeatable_without_a_prebuilt_runtime_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.env"
            path.write_text("POSTGRES_PASSWORD=keep-this\n")
            ensure_dependency_environment(path)
            first = path.read_bytes()
            ensure_dependency_environment(path)
            self.assertEqual(path.read_bytes(), first)
            values = runtime_values(path)
            self.assertEqual(values["POSTGRES_PASSWORD"], "keep-this")
            self.assertNotIn("BRIAREUS_RUNTIME_BASE", values)
            self.assertNotIn("BRIAREUS_GHIDRA_ENGINE_TOKEN", values)
            self.assertNotIn("GHIDRA_MCP_URL", values)
            self.assertNotIn("GHIDRA_DIRECT_UPLOAD_URL", values)
