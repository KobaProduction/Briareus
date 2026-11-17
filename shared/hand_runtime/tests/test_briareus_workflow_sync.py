"""Contract tests for build-synchronized external workflow documents."""

from __future__ import annotations

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from briareus_hand_runtime.hand_workflows import hand_version, register_hand_workflow
from briareus_hand_runtime.workflow_sync import (
    DEPLOY_PATHS,
    GIT_PATHS,
    fetch_source,
    install_snapshot,
    select_documents,
)
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.skills import SkillsClientExtension

SHA = "abcdef1234567890abcdef1234567890abcdef12"


def archive_for(bundle: str, extra: dict[str, bytes] | None = None) -> bytes:
    paths = (
        GIT_PATHS
        if bundle == "git"
        else (*DEPLOY_PATHS, "skills/services-deployment/README.md",
              "skills/services-deployment/coolify-compose.md")
    )
    files = {path: f"# {path}\n".encode() for path in paths}
    files.update(extra or {})
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w:gz") as stream:
        for name, data in files.items():
            member = tarfile.TarInfo(f"ai-agent-workflow-{SHA}/{name}")
            member.size = len(data)
            stream.addfile(member, io.BytesIO(data))
    return result.getvalue()


class SyncValidation(unittest.TestCase):
    def test_bundle_extracts_only_allowed_files_and_records_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = archive_for(
                "coolify",
                {"skills/services-deployment/coolify-secrets.md": b"# secrets\n",
                 "secret.txt": b"do not extract"},
            )
            destination = install_snapshot("coolify", SHA, archive, root)
            source = json.loads((destination / "SOURCE.json").read_text())
            self.assertEqual(source["revision"], SHA)
            self.assertEqual(source["repository"], "ArthurKoba/ai-agent-workflow")
            self.assertEqual(source["bundle"], "coolify")
            self.assertEqual(len(source["files"]), len(DEPLOY_PATHS) + 3)
            self.assertFalse((destination / "references" / "secret.txt").exists())
            self.assertIn(SHA, (destination / "SKILL.md").read_text())
            self.assertEqual(
                (destination / "references/skills/services-deployment/coolify-secrets.md")
                .read_text(),
                "# secrets\n",
            )

    def test_missing_required_source_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "Missing mandatory"):
            select_documents("git", archive_for("coolify"))

    def test_archive_does_not_allow_traversal(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsafe archive member"):
            select_documents("git", archive_for("git", {"../../outside.md": b"bad"}))

    def test_revision_must_be_resolved_commit(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(ValueError, "Invalid bundle or revision"),
        ):
            install_snapshot("git", "main", archive_for("git"), Path(directory))

    def test_fetch_ref_file_uses_immutable_revision_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.json"
            reference.write_text(json.dumps({"object": {"sha": SHA}}))
            mock_archive = archive_for("git")
            with patch(
                "briareus_hand_runtime.workflow_sync.read_url", return_value=mock_archive
            ) as reader:
                revision, downloaded = fetch_source(reference)
            self.assertEqual(revision, SHA)
            self.assertEqual(downloaded, mock_archive)
            self.assertEqual(
                reader.call_args.args[0],
                "https://codeload.github.com/ArthurKoba/ai-agent-workflow/tar.gz/" + SHA,
            )


class ImportedSkillContract(unittest.IsolatedAsyncioTestCase):
    async def test_git_and_coolify_bundles_expose_protocol_and_read_only_tool(self) -> None:
        for bundle in ("git", "coolify"):
            with self.subTest(bundle=bundle), tempfile.TemporaryDirectory() as directory:
                    source = Path(directory)
                    work = source / "provider"
                    skill = work / "skills" / "test-workflow" / "SKILL.md"
                    skill.parent.mkdir(parents=True)
                    skill.write_text(
                        "---\nname: test-workflow\n"
                        'description: "Test provider workflow."\n'
                        "---\n\n# Main\n",
                        encoding="utf-8",
                    )
                    installed = install_snapshot(bundle, SHA, archive_for(bundle), source)
                    share = installed.parent
                    if bundle == "git":
                        publishing = share / "source-control-publishing" / "SKILL.md"
                        publishing.parent.mkdir(parents=True)
                        publishing.write_text(
                            "---\nname: source-control-publishing\n"
                            "description: shared publication workflow\n---\n"
                        )
                    provider_mock = (
                        "briareus_hand_runtime.hand_workflows._shared_publishing_root"
                        if bundle == "git"
                        else "briareus_hand_runtime.hand_workflows._shared_deployment_root"
                    )
                    with (
                        patch(provider_mock, return_value=share),
                        patch.dict("os.environ", {"SOURCE_COMMIT": SHA}, clear=True),
                    ):
                        mcp = FastMCP("test")
                        register_hand_workflow(
                            mcp, work, "test-workflow",
                            shared_publishing=bundle == "git",
                            shared_deployment=bundle == "coolify",
                        )
                        version = hand_version(
                            work,
                            shared_publishing=bundle == "git",
                            shared_deployment=bundle == "coolify",
                        )
                        self.assertIn("-workflow-abcdef123456", version)
                        async with Client(mcp, extensions=[SkillsClientExtension()]) as client:
                            skills = await client.list_skills()
                            names = {item.frontmatter.name for item in skills}
                            imported_name = (
                                "ai-agent-git-workflow" if bundle == "git"
                                else "ai-agent-services-deployment"
                            )
                            self.assertIn(imported_name, names)
                            self.assertIn("test-workflow", names)
                            refpath = (
                                "skills/git-workflow.md" if bundle == "git"
                                else "skills/services-deployment/README.md"
                            )
                            result = await client.call_tool(
                                "read_workflow_reference",
                                {"bundle": bundle, "path": refpath},
                            )
                            self.assertFalse(result.is_error)
                            self.assertEqual(result.content[0].text, "# " + refpath + "\n")
                            with self.assertRaisesRegex(ToolError, "Invalid workflow"):
                                await client.call_tool(
                                    "read_workflow_reference",
                                    {"bundle": bundle, "path": "../../secret.md"},
                                )

    async def test_require_synced_bundle_missing_fails_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            skill = source / "skills" / "test" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: test\ndescription: test\n---\n")
            with (
                patch.dict("os.environ", {"BRIAREUS_REQUIRE_SYNCED_SKILLS": "true"}),
                patch(
                    "briareus_hand_runtime.hand_workflows._shared_deployment_root",
                    return_value=source / "missing",
                ),self.assertRaisesRegex(FileNotFoundError, "build-synchronized")
            ):
                register_hand_workflow(
                    FastMCP("test"), source, "test", shared_deployment=True
                )
