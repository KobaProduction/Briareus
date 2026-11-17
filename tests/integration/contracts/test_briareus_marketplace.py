"""Independent Briareus V1 marketplace: one native Skill, no AI Workflow copies."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "briareus_marketplace", ROOT / "scripts/briareus_marketplace.py"
)
assert SPEC is not None and SPEC.loader is not None
MARKET = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MARKET)


class MarketplaceContracts(unittest.TestCase):
    def test_one_plugin_with_one_skill(self) -> None:
        root = ROOT / "plugins/briareus-v1"
        market = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual(len(market["plugins"]), 1)
        self.assertEqual(market["plugins"][0]["name"], "briareus-v1")
        for manifest in ("plugin.json", ".codex-plugin/plugin.json"):
            data = json.loads((root / manifest).read_text())
            self.assertEqual(data["name"], "briareus-v1")
            self.assertEqual(data["skills"], "./skills/")
        paths = list((root / "skills").glob("*/SKILL.md"))
        self.assertEqual(len(paths), 1)
        content = paths[0].read_text(encoding="utf-8")
        self.assertLess(len(content), 5000)
        self.assertIn("name: briareus-v1", content)
        self.assertIn("references/docs/operations", content)
        self.assertFalse((root / "skills/ai-agent-git-workflow").exists())
        for name in MARKET.DEPRECATED:
            self.assertFalse((ROOT / "plugins" / name).exists())

    def test_official_brand_icon_is_packaged_without_modification(self) -> None:
        from xml.etree import ElementTree

        root = ROOT / "plugins/briareus-v1"
        original = ROOT / "assets/brand/base/briareus.svg"
        packaged = root / "assets/briareus.svg"
        self.assertEqual(packaged.read_bytes(), original.read_bytes())
        vector = ElementTree.fromstring(packaged.read_bytes())
        self.assertEqual(vector.get("width"), "1024")
        self.assertEqual(vector.get("height"), "1024")
        self.assertEqual(vector.get("viewBox"), "0 0 1024 1024")
        self.assertLess(packaged.stat().st_size, 5 * 1024 * 1024)
        for manifest in ("plugin.json", ".codex-plugin/plugin.json"):
            data = json.loads((root / manifest).read_text(encoding="utf-8"))
            interface = (
                data["extensions"]["com.openai"]["interface"]
                if manifest == "plugin.json"
                else data["interface"]
            )
            for key in ("logo", "composerIcon"):
                self.assertEqual(interface[key], "./assets/briareus.svg")
                self.assertTrue((root / interface[key]).is_file())

    def test_source_provenance_and_service_ownership(self) -> None:
        root = ROOT / "plugins/briareus-v1/skills/briareus-v1"
        source = json.loads((root / "SOURCE.json").read_text())
        catalogue = json.loads((ROOT / "deploy/services.json").read_text())
        self.assertEqual(source["repository"], "KobaProduction/Briareus")
        for entry in catalogue["services"]:
            readme = f"{entry['directory']}/README.md"
            self.assertIn(readme, source["files"])
        self.assertIn("AGENTS.md", source["files"])
        self.assertIn("docs/operations/testing.md", source["files"])
        for path, checksum in source["files"].items():
            file = root / "references" / path
            self.assertEqual(checksum, hashlib.sha256(file.read_bytes()).hexdigest())
        for path, checksum in source["original_files"].items():
            self.assertEqual(checksum, hashlib.sha256((ROOT / path).read_bytes()).hexdigest())

    def test_marketplace_skill_routes_all_mcp_hands_without_git_clone(self) -> None:
        skill = (ROOT / "plugins/briareus-v1/skills/briareus-v1/SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("any Briareus V1 MCP connection", skill)
        self.assertIn("read_project_workflow", skill)
        self.assertIn("Do not require a checkout", skill)
        self.assertIn("references/docs/hands/analysis.md", skill)
        self.assertIn("references/docs/hands/telemetry.md", skill)

    def test_repeated_mcp_failures_route_to_owned_bundled_diagnostics(self) -> None:
        names = (
            "README.md",
            "server.md",
            "source-control.md",
            "authentication.md",
            "runtime.md",
            "coolify.md",
        )
        source_dir = ROOT / "docs/hands/troubleshooting"
        packaged = (
            ROOT / "plugins/briareus-v1/skills/briareus-v1/references/docs/hands/troubleshooting"
        )
        skill = (ROOT / "plugins/briareus-v1/skills/briareus-v1/SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("references/docs/hands/troubleshooting/README.md", skill)
        self.assertIn("Before a checkout", skill)
        self.assertIn("preventive checks", skill)
        owner_index = (ROOT / "docs/hands/README.md").read_text(encoding="utf-8")
        self.assertIn("(troubleshooting/README.md)", owner_index)

        incident_ids = ("#252", "#367", "#370", "#428", "#555", "#554")
        combined = []
        for name in names:
            with self.subTest(guide=name):
                owner = source_dir / name
                bundled = packaged / name
                self.assertTrue(owner.is_file())
                self.assertEqual(owner.read_bytes(), bundled.read_bytes())
                self.assertLess(len(owner.read_text(encoding="utf-8")), 5000)
                combined.append(owner.read_text(encoding="utf-8"))
        material = "\n".join(combined)
        for issue in incident_ids:
            self.assertIn(issue, material)
        self.assertIn("AI Agent Workflow", material)
        self.assertIn("not", material)
        self.assertNotIn("skills/terminal-operations.md", skill)
        self.assertFalse(
            (ROOT / "plugins/briareus-v1/skills/briareus-v1/references/skills").exists()
        )

    def test_provider_dockerfiles_do_not_fetch_external_workflow(self) -> None:
        for relative in (
            "services/hands/svc/github/Dockerfile",
            "services/hands/svc/gitlab/Dockerfile",
            "services/hands/infrastructure/coolify/Dockerfile",
        ):
            with self.subTest(dockerfile=relative):
                content = (ROOT / relative).read_text(encoding="utf-8")
                self.assertNotIn("ai-agent-workflow", content)
                self.assertNotIn("BRIAREUS_REQUIRE_SYNCED_SKILLS", content)
                self.assertNotIn("workflow_sync", content)
        for removed in (
            "shared/hand_runtime/src/briareus_hand_runtime/workflow_sync.py",
            ".github/workflows/ai-agent-workflow-dispatch.yml",
        ):
            self.assertFalse((ROOT / removed).exists())

    def test_project_skill_publisher_is_local_and_push_driven(self) -> None:
        workflow = (ROOT / ".github/workflows/publish-plugin-marketplace.yml").read_text()
        self.assertIn("branches: [v1]", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("python3 scripts/briareus_marketplace.py", workflow)
        self.assertIn("git push origin HEAD:v1", workflow)
        self.assertIn("if git diff --cached --quiet", workflow)
        self.assertNotIn("BRIAREUS_DISPATCH_TOKEN", workflow)
        self.assertNotIn("ai-agent-workflow", workflow)
        self.assertFalse((ROOT / ".github/workflows/ai-agent-workflow-dispatch.yml").exists())

    def test_generator_detects_drift(self) -> None:
        self.assertEqual(MARKET.update(check=True), (0, 0))
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(MARKET, "ROOT", Path(temp)),
            patch.object(
                MARKET,
                "generated_files",
                return_value={Path("plugins/briareus-v1/plugin.json"): b"{}"},
            ),
        ):
            entry = Path("plugins/briareus-v1/plugin.json")
            self.assertEqual(MARKET.update(check=False), (1, 0))
            self.assertEqual(MARKET.update(check=True), (0, 0))
            (Path(temp) / entry).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "Marketplace drift"):
                MARKET.update(check=True)


if __name__ == "__main__":
    unittest.main()
