from __future__ import annotations

import fnmatch
import json
import unittest
from dataclasses import dataclass
from pathlib import Path

from bri_catalog import source_closure
from ci_plan import plan

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
    def test_ui_and_application_changes_do_not_redeploy_stable_dependencies(self) -> None:
        self.assertEqual(consumers("control-panel-ui/src/app/App.vue"), {"control-panel-ui"})
        self.assertEqual(consumers("src/modules/web/browser.py"), {"web"})
        self.assertEqual(consumers("src/browser_runtime/process.py"), {"chromium"})
        self.assertNotIn("chromium", consumers("src/modules/web/browser.py"))
        for source in (ROOT / "src").rglob("*.py"):
            selected = consumers(source.relative_to(ROOT).as_posix())
            self.assertFalse(selected & {"dependencies", "identity"})

    def test_shared_identity_transport_only_selects_actual_identity_consumers(self) -> None:
        self.assertEqual(
            consumers("src/common/identity_provider.py"),
            {"auth", "control-panel-api"},
        )
        self.assertTrue({"web", "chromium"}.issubset(consumers("src/common/browser_extensions.py")))
        self.assertFalse(
            {"files", "github", "gitlab", "terminal"}
            & consumers("src/common/browser_extensions.py")
        )

    def test_every_imported_local_source_is_watched_by_its_owning_deployment(self) -> None:
        owners = {
            "auth": "auth_service",
            "gateway": "gateway",
            "control-panel-api": "control_panel_api",
            "chromium": "browser_runtime",
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
                    self.assertFalse(set(closure) - set(unit.watchers))
                    self.assertNotIn("src/common/**", unit.watchers)
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
            ["test_bri_deployment_boundaries"],
        )
        self.assertEqual(plan(["control-panel-ui/src/app/App.vue"])["contract_modules"], [])

    def test_ci_full_and_shared_fixture_plans_name_every_existing_suite(self) -> None:
        expected = sorted(path.stem for path in (ROOT / "tests").glob("test_*.py"))
        self.assertTrue(expected)
        for paths in (["uv.lock"], ["tests/bri_mcp_support.py"], [".github/workflows/ci.yaml"]):
            with self.subTest(paths=paths):
                actual = plan(paths)["contract_modules"]
                self.assertIsInstance(actual, list)
                self.assertEqual(sorted(actual), expected)
