"""Codex marketplace layout, supply-chain safety and idempotent skill publication."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/briareus_marketplace.py"
SPEC = importlib.util.spec_from_file_location("briareus_marketplace", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MARKET = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MARKET)
REVISION = "a" * 40


class MarketplaceContracts(unittest.TestCase):
    def test_valid_codex_marketplace_and_portable_plugins(self) -> None:
        # Check the same root and source paths consumed by the Codex importer.
        manifest = ROOT / ".agents/plugins/marketplace.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload["name"], "briareus-v1")
        self.assertEqual(len(payload["plugins"]), 4)
        for entry in payload["plugins"]:
            self.assertEqual(entry["source"]["source"], "local")
            self.assertEqual(entry["policy"]["installation"], "AVAILABLE")
            self.assertEqual(entry["policy"]["authentication"], "ON_INSTALL")
            relative = entry["source"]["path"]
            self.assertTrue(relative.startswith("./plugins/briareus-"))
            base = ROOT / relative
            self.assertTrue(base.resolve().is_relative_to(ROOT))
            portable = json.loads((base / "plugin.json").read_text())
            codex = json.loads((base / ".codex-plugin/plugin.json").read_text())
            self.assertEqual(portable["name"], entry["name"])
            self.assertEqual(codex["name"], entry["name"])
            self.assertEqual(codex["skills"], "./skills/")
            self.assertTrue(list((base / "skills").glob("*/SKILL.md")))

    def test_packaged_sources_preserve_hashes_and_local_owner_skills(self) -> None:
        for plugin, (name, source) in MARKET.PROVIDER_SKILLS.items():
            root = ROOT / "plugins" / f"briareus-{plugin}-workflows" / "skills"
            self.assertEqual((root / name / "SKILL.md").read_bytes(), (ROOT / source).read_bytes())
            if plugin in {"github", "gitlab"}:
                self.assertEqual(
                    (root / "source-control-publishing/SKILL.md").read_bytes(),
                    (ROOT / MARKET.SHARED_SKILL).read_bytes(),
                )
            if plugin == "server":
                continue
            bundle = "coolify" if plugin == "coolify" else "git"
            imported = (
                "ai-agent-services-deployment" if bundle == "coolify" else "ai-agent-git-workflow"
            )
            snapshot = root / imported
            provenance = json.loads((snapshot / "SOURCE.json").read_text())
            self.assertEqual(provenance["repository"], "ArthurKoba/ai-agent-workflow")
            self.assertRegex(provenance["revision"], r"\A[0-9a-f]{40}\Z")
            self.assertTrue(set(MARKET.mandatory_paths(bundle)).issubset(provenance["files"]))
            for path, checksum in provenance["files"].items():
                actual = (snapshot / "references" / path).read_bytes()
                self.assertEqual(checksum, hashlib.sha256(actual).hexdigest())
            self.assertIn(
                provenance["revision"], (snapshot / "SKILL.md").read_text(encoding="utf-8")
            )

    def test_update_check_reports_drift_then_reconciles_without_touching_other_plugins(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(MARKET, "ROOT", root):
                expected = {
                    Path("plugins/briareus-server-workflows/plugin.json"): b"{}",
                    Path(".agents/plugins/marketplace.json"): b'{"name":"sample"}',
                }
                self.assertEqual(len(MARKET.reconcile(expected, check=False)), 2)
                self.assertEqual(MARKET.reconcile(expected, check=True), [])
                unrelated = root / "plugins/unrelated-plugin/notes.md"
                unrelated.parent.mkdir(parents=True)
                unrelated.write_text("leave intact", encoding="utf-8")
                expected[Path("plugins/briareus-server-workflows/plugin.json")] = b'{"version":2}'
                with self.assertRaisesRegex(ValueError, "out of sync"):
                    MARKET.reconcile(expected, check=True)
                self.assertEqual(len(MARKET.reconcile(expected, check=False)), 1)
                self.assertEqual(MARKET.reconcile(expected, check=True), [])
                self.assertEqual(unrelated.read_text(), "leave intact")

    def test_pinned_checkout_rejects_invalid_and_unrelated_git_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            for path in set(MARKET.mandatory_paths("git")) | set(MARKET.mandatory_paths("coolify")):
                file = repo / path
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(f"# {path}\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.test",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                check=True,
            )
            sha = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
            ).strip()
            docs = MARKET.upstream_documents(repo, sha)
            self.assertEqual(docs["git"]["AGENTS.md"], b"# AGENTS.md\n")
            self.assertIn("skills/services-deployment/README.md", docs["coolify"])
            with self.assertRaisesRegex(ValueError, "40-character"):
                MARKET.upstream_documents(repo, "main")
            with self.assertRaises(ValueError):
                MARKET.upstream_documents(repo, REVISION)


if __name__ == "__main__":
    unittest.main()
