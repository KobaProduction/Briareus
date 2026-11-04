from __future__ import annotations

import json
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Protocol, cast
from unittest.mock import patch

from briareus_dockerfiles import dockerignore, image_paths, standalone_dockerfile
from briareus_local import ensure_dependency_environment, runtime_values

from scripts.briareus_coolify import load_model, mapping

ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "deploy/services.json").is_file()
)


class SourceFetcher(Protocol):
    def fetch_source(self, pin_path: Path, destination: Path) -> None: ...


def source_fetch_module() -> SourceFetcher:
    path = ROOT / "services/dependencies/ghidra-mcp/fetch_source.py"
    spec = spec_from_file_location("ghidra_build_source", path)
    if spec is None or spec.loader is None:
        raise AssertionError("The pinned Ghidra source adapter is missing")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(SourceFetcher, module)


class CoolifyPackagingContracts(unittest.TestCase):
    def test_each_python_image_has_the_current_self_contained_dependency_recipe(self) -> None:
        paths = image_paths()
        self.assertEqual(len(paths), 9)
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
            "ZITADEL_CLIENT_SECRET",
            "MCP_OAUTH_JWT_SIGNING_KEY",
            "MCP_OAUTH_INTROSPECTION_TOKEN",
        ):
            self.assertEqual(environment[key], "${" + key + ":?}")
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
                    self.assertIn("${DEPLOYMENT_ENVIRONMENT:?}", name)
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

    def test_source_fetch_rejects_moving_refs_before_running_git(self) -> None:
        module = source_fetch_module()
        fetch = module.fetch_source
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "source.json"
            path.write_text(
                json.dumps(
                    {
                        "repository": "https://github.com/ArthurKoba/ghidra-mcp.git",
                        "revision": "main",
                    }
                )
            )
            with patch("subprocess.run") as run, self.assertRaisesRegex(ValueError, "immutable"):
                fetch(path, root / "vendor")
            run.assert_not_called()
            self.assertFalse((root / "vendor").exists())
