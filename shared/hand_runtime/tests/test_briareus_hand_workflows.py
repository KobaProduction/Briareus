"""Briareus-owned MCP Skills, fallback surfaces and revision identity."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from briareus_hand_runtime.hand_workflows import hand_version, register_hand_workflow
from briareus_hand_runtime.runtime_common import build_private_mcp
from fastmcp import Client, FastMCP
from fastmcp.skills import SkillsClientExtension

ROOT = Path(__file__).resolve().parents[3]
HAND_SKILLS = (
    ("services/hands/server/src/briareus_server", "server-project-workflow", False),
    ("services/hands/svc/github/src/briareus_github", "github-repository-workflow", True),
    ("services/hands/svc/gitlab/src/briareus_gitlab", "gitlab-repository-workflow", True),
    (
        "services/hands/infrastructure/coolify/src/briareus_coolify",
        "coolify-deployment-workflow",
        False,
    ),
)


class HandVersionTests(unittest.TestCase):
    def test_source_commit_from_deployment_environment(self) -> None:
        with patch.dict("os.environ", {"SOURCE_COMMIT": "A1B2C3D4E5F6A7B8"}, clear=True):
            self.assertEqual(hand_version(ROOT), "git-a1b2c3d4e5f6")
            self.assertEqual(hand_version(ROOT, shared_publishing=True), "git-a1b2c3d4e5f6")

    def test_shared_constructor_exposes_version_and_instructions(self) -> None:
        with (
            patch("briareus_hand_runtime.runtime_common.build_observability"),
            patch("briareus_hand_runtime.runtime_common.announce_runtime_started"),
        ):
            mcp = build_private_mcp(
                "server",
                instructions="Read the Briareus-specific Skill",
                version="git-abcdef123456",
            )
        self.assertEqual(mcp.version, "git-abcdef123456")
        self.assertEqual(mcp.instructions, "Read the Briareus-specific Skill")

    def test_local_shared_policy_changes_source_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            source.joinpath("runtime.py").write_text("unchanged", encoding="utf-8")
            policy_root = source / "skills"
            policy_root.mkdir()
            policy = policy_root / "SKILL.md"
            policy.write_text("first", encoding="utf-8")
            with (
                patch.dict("os.environ", {}, clear=True),
                patch(
                    "briareus_hand_runtime.hand_workflows._shared_publishing_root",
                    return_value=policy_root,
                ),
            ):
                old = hand_version(source, shared_publishing=True)
                policy.write_text("second", encoding="utf-8")
                self.assertNotEqual(old, hand_version(source, shared_publishing=True))

    def test_fingerprint_ignores_irrelevant_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "runtime.py"
            source.write_text("first", encoding="utf-8")
            with patch.dict("os.environ", {}, clear=True):
                first = hand_version(root)
                self.assertTrue(first.startswith("src-"))
                source.write_text("second", encoding="utf-8")
                self.assertNotEqual(first, hand_version(root))
                unchanged = hand_version(root)
                (root / "runtime.pyc").write_bytes(b"noise")
                self.assertEqual(unchanged, hand_version(root))


class HandSkillContracts(unittest.IsolatedAsyncioTestCase):
    async def test_four_hands_publish_only_local_skills_resources_prompts_tools(self) -> None:
        for relative, skill_name, publishing in HAND_SKILLS:
            with self.subTest(hand=skill_name):
                source = ROOT / relative
                mcp = FastMCP(
                    name=skill_name,
                    instructions=f"Use skill://{skill_name}/SKILL.md",
                    version=hand_version(source, shared_publishing=publishing),
                )
                register_hand_workflow(mcp, source, skill_name, shared_publishing=publishing)
                async with Client(mcp, extensions=[SkillsClientExtension()]) as client:
                    self.assertIn(
                        "io.modelcontextprotocol/skills",
                        client.server_capabilities.extensions,
                    )
                    uri = f"skill://{skill_name}/SKILL.md"
                    expected = {uri}
                    if publishing:
                        expected.add("skill://source-control-publishing/SKILL.md")
                    entries = await client.list_skills()
                    self.assertEqual({str(item.uri) for item in entries}, expected)
                    self.assertEqual((await client.get_skill(uri)).frontmatter.name, skill_name)

                    resources = await client.list_resources()
                    self.assertTrue(expected.issubset({str(item.uri) for item in resources}))
                    resource = await client.read_resource(uri)
                    self.assertIn("name: " + skill_name, str(resource))
                    self.assertNotIn(
                        "https://github.com/ArthurKoba/ai-agent-workflow", str(resource)
                    )
                    if publishing:
                        shared = await client.get_skill(
                            "skill://source-control-publishing/SKILL.md"
                        )
                        self.assertEqual(shared.frontmatter.name, "source-control-publishing")
                        shared_resource = await client.read_resource(
                            "skill://source-control-publishing/SKILL.md"
                        )
                        self.assertIn("integration branch", str(shared_resource))

                    tools = {item.name for item in await client.list_tools()}
                    self.assertIn("read_project_workflow", tools)
                    self.assertNotIn("read_workflow_reference", tools)
                    self.assertIn(
                        "project_workflow",
                        {item.name for item in await client.list_prompts()},
                    )
                    response = await client.call_tool("read_project_workflow", {})
                    self.assertFalse(response.is_error)
                    self.assertIn("name: " + skill_name, response.content[0].text)
                    self.assertNotIn(
                        "https://github.com/ArthurKoba/ai-agent-workflow",
                        response.content[0].text,
                    )
                    prompt = await client.get_prompt("project_workflow")
                    self.assertIn("name: " + skill_name, prompt.messages[0].content.text)

    async def test_fallback_without_skills_extension(self) -> None:
        for relative, name, publishing in HAND_SKILLS:
            with self.subTest(hand=name):
                mcp = FastMCP(name)
                register_hand_workflow(mcp, ROOT / relative, name, shared_publishing=publishing)
                async with Client(mcp) as client:
                    result = await client.call_tool("read_project_workflow", {})
                    self.assertFalse(result.is_error)
                    self.assertIn("name: " + name, result.content[0].text)
                    if publishing:
                        self.assertIn("source-control-publishing", result.content[0].text)

    async def test_missing_local_provider_skill_fails_closed(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            self.assertRaisesRegex(FileNotFoundError, "Required Briareus Hand skill"),
        ):
            register_hand_workflow(FastMCP("missing"), Path(tmp), "missing-skill")
