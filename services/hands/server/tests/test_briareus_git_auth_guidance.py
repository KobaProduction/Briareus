from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock

from briareus_json_values import JsonObject
from briareus_server.terminal.git_guidance import with_git_auth_guidance
from briareus_service_catalog import service_definition
from briareus_service_discovery import DiscoveredService, DiscoverySnapshot, ServiceDiscovery


def discovery_for(*connected: str) -> MagicMock:
    discovery = MagicMock(spec=ServiceDiscovery)
    discovery.snapshot.return_value = DiscoverySnapshot(
        services=tuple(
            DiscoveredService(
                id=name, name=service_definition(name).name, group="svc",
                connected=name in connected, mcp_path=service_definition(name).mcp_path,
            )
            for name in ("github", "gitlab")
        ),
        checked_at=datetime.now(UTC),
    )
    return discovery


class GitAuthGuidanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_four_provider_combinations_only_include_available_services(self) -> None:
        for providers in ((), ("github",), ("gitlab",), ("github", "gitlab")):
            with self.subTest(providers=providers):
                result: JsonObject = {"exit_code": 128, "stderr": "fatal: Authentication failed"}
                discovery = discovery_for(*providers)
                updated = await with_git_auth_guidance(result, discovery=discovery)
                discovery.snapshot.assert_awaited_once()
                if not providers:
                    self.assertIs(updated, result)
                    self.assertNotIn("git_auth_hint", updated)
                    continue
                hint = updated["git_auth_hint"]
                assert isinstance(hint, dict)
                for name in ("github", "gitlab"):
                    self.assertEqual(name in hint, name in providers)
                    if name not in providers:
                        self.assertNotIn(name, str(hint).casefold())

    async def test_availability_changes_are_used_without_restarting_server(self) -> None:
        result: JsonObject = {"exit_code": 128, "stderr": "fatal: Authentication failed"}
        discovery = discovery_for("github")
        first = await with_git_auth_guidance(result, discovery=discovery)
        self.assertIn("github_authorize_local_git", str(first["git_auth_hint"]))
        discovery.snapshot.return_value = discovery_for("gitlab").snapshot.return_value
        second = await with_git_auth_guidance(result, discovery=discovery)
        self.assertNotIn("github", str(second["git_auth_hint"]))
        self.assertIn("authorize_local_git", str(second["git_auth_hint"]))

    async def test_failed_git_auth_keeps_original_output_and_names_exact_arguments(self) -> None:
        for error in (
            "fatal: could not read Username for 'https://github.com': terminal prompts disabled",
            "fatal: Authentication failed for 'https://git.example.test/group/repo.git/'",
            "remote: HTTP Basic: Access denied",
            "git@github.com: Permission denied (publickey).",
        ):
            with self.subTest(error=error):
                result: JsonObject = {"exit_code": 128, "stdout": "", "stderr": error}
                updated = await with_git_auth_guidance(
                    result, discovery=discovery_for("github", "gitlab")
                )
                self.assertEqual(updated["stderr"], error)
                hint = updated["git_auth_hint"]
                assert isinstance(hint, dict)
                self.assertIn("repository", str(hint["github"]))
                self.assertIn("project", str(hint["gitlab"]))
                self.assertIn("destination", str(hint))
                self.assertNotIn("git_auth_hint", result)

    async def test_unavailable_or_failed_discovery_preserves_the_git_failure(self) -> None:
        result: JsonObject = {"exit_code": 128, "stderr": "fatal: Authentication failed"}
        self.assertIs(await with_git_auth_guidance(result), result)
        for error in (TimeoutError(), RuntimeError("registry unavailable")):
            discovery = discovery_for("github", "gitlab")
            discovery.snapshot.side_effect = error
            self.assertIs(await with_git_auth_guidance(result, discovery=discovery), result)

    async def test_non_auth_failures_success_timeouts_and_running_jobs_never_probe(self) -> None:
        results: list[JsonObject] = [
            {"exit_code": 1, "stderr": message}
            for message in (
                "fatal: unable to access remote: Connection reset by peer",
                "fatal: Could not resolve host: github.com",
                "remote: protected branch hook declined",
                "fatal: repository not found",
                "npm ERR! Authentication failed",
            )
        ]
        results.extend([
            {"exit_code": 0, "stderr": "fatal: Authentication failed"},
            {"exit_code": 128, "timed_out": True, "stderr": "fatal: Authentication failed"},
            {"state": "running", "output": "fatal: Authentication failed"},
        ])
        discovery = discovery_for("github", "gitlab")
        for result in results:
            self.assertIs(await with_git_auth_guidance(result, discovery=discovery), result)
        discovery.snapshot.assert_not_awaited()

    async def test_failed_job_filters_providers_without_copying_secret_output(self) -> None:
        result: JsonObject = {
            "state": "failed", "output": "fatal: Authentication failed private-fixture-token",
        }
        updated = await with_git_auth_guidance(result, discovery=discovery_for("gitlab"))
        self.assertNotIn("private-fixture-token", str(updated["git_auth_hint"]))
        self.assertNotIn("github", str(updated["git_auth_hint"]))
        self.assertEqual(updated["output"], result["output"])
