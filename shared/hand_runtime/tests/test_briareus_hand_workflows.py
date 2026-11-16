"""MCP workflow skills, fallback surfaces, and runtime revision contract."""

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
)


class HandVersionTests(unittest.TestCase):
    def test_git_commit_from_deployment_environment(self) -> None:
        with patch.dict("os.environ", {"SOURCE_COMMIT": "A1B2C3D4E5F6A7B8"}, clear=True):
            self.assertEqual(hand_version(ROOT), "git-a1b2c3d4e5f6")

    def test_shared_constructor_exposes_explicit_server_version_and_instructions(self) -> None:
        with (
            patch("briareus_hand_runtime.runtime_common.build_observability"),
            patch("briareus_hand_runtime.runtime_common.announce_runtime_started"),
        ):
            mcp = build_private_mcp(
                "server",
                instructions="Read the canonical project skill",
                version="git-abcdef123456",
            )
        self.assertEqual(mcp.version, "git-abcdef123456")
        self.assertEqual(mcp.instructions, "Read the canonical project skill")

    def test_shared_policy_changes_source_fingerprint(self) -> None:
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

    def test_fallback_changes_when_source_changes(self) -> None:
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
    async def test_three_hands_publish_skills_resources_prompts_and_tools(self) -> None:
        for relative, skill_name, shared_publishing in HAND_SKILLS:
            with self.subTest(hand=skill_name):
                source = ROOT / relative
                mcp = FastMCP(
                    name=skill_name,
                    instructions=f"Use skill://{skill_name}/SKILL.md",
                    version=hand_version(source, shared_publishing=shared_publishing),
                )
                register_hand_workflow(
                    mcp, source, skill_name, shared_publishing=shared_publishing
                )
                async with Client(mcp, extensions=[SkillsClientExtension()]) as client:
                    self.assertIn(
                        "io.modelcontextprotocol/skills",
                        client.server_capabilities.extensions,
                    )
                    entry = await client.list_skills()
                    uri = f"skill://{skill_name}/SKILL.md"
                    expected = {uri}
                    if shared_publishing:
                        expected.add("skill://source-control-publishing/SKILL.md")
                    self.assertEqual({str(item.uri) for item in entry}, expected)
                    self.assertEqual((await client.get_skill(uri)).frontmatter.name, skill_name)
                    resources = await client.list_resources()
                    self.assertTrue(expected.issubset({str(item.uri) for item in resources}))
                    raw_resource = await client.read_resource(uri)
                    self.assertIn("name: " + skill_name, str(raw_resource))
                    if shared_publishing:
                        shared_uri = "skill://source-control-publishing/SKILL.md"
                        shared_entry = await client.get_skill(shared_uri)
                        self.assertEqual(shared_entry.frontmatter.name, "source-control-publishing")
                        shared_resource = await client.read_resource(shared_uri)
                        self.assertIn("direct push to", str(shared_resource))
                    self.assertIn(
                        "read_project_workflow",
                        {item.name for item in await client.list_tools()},
                    )
                    self.assertIn(
                        "project_workflow",
                        {item.name for item in await client.list_prompts()},
                    )
                    result = await client.call_tool("read_project_workflow", {})
                    self.assertFalse(result.is_error)
                    self.assertIn("name: " + skill_name, result.content[0].text)
                    prompt = await client.get_prompt("project_workflow")
                    self.assertIn(
                        "name: " + skill_name,
                        prompt.messages[0].content.text,
                    )

                    if shared_publishing:
                        for payload in (result.content[0].text, prompt.messages[0].content.text):
                            self.assertIn("Publication default: direct push to", payload)
                            self.assertIn("Fallback to PR/MR only", payload)
                            self.assertIn("If the user expressly forbids PR/MR creation", payload)

    async def test_shared_publishing_fallback_without_skills_extension(self) -> None:
        for relative, skill_name, shared in HAND_SKILLS[1:]:
            with self.subTest(skill_name=skill_name):
                mcp = FastMCP(skill_name)
                register_hand_workflow(mcp, ROOT / relative, skill_name, shared_publishing=shared)
                async with Client(mcp) as client:
                    response = await client.call_tool("read_project_workflow", {})
                    self.assertFalse(response.is_error)
                    self.assertIn("Publication default: direct push to", response.content[0].text)

    async def test_fallback_tool_available_without_skills_extension(self) -> None:
        source = ROOT / HAND_SKILLS[0][0]
        mcp = FastMCP("fallback")
        register_hand_workflow(mcp, source, HAND_SKILLS[0][1])
        async with Client(mcp) as client:
            names = {item.name for item in await client.list_tools()}
            self.assertIn("read_project_workflow", names)
            result = await client.call_tool("read_project_workflow", {})
            self.assertFalse(result.is_error)
            self.assertIn("canonical checkout", result.content[0].text)
