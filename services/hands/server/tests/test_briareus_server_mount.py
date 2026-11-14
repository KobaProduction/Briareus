from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from briareus_account_contracts import AccountList, ResolvedAccount
from briareus_control_panel_client.control_panel_client import ControlPanelClient
from briareus_git.repository_checkout import (
    RepositoryCheckoutError,
    _destination,
    checkout_destination,
)
from briareus_github.github_agent import GitHubAgentError, GitHubAppClient
from briareus_github.github_identity import GitHubPrettyIdentityClient
from briareus_github.settings import GitHubPolicySettings
from briareus_github.tool_context import GitHubRuntimeContext
from briareus_gitlab.api import GitLabApiClient
from briareus_gitlab.errors import GitLabError
from briareus_gitlab.models import GitLabProfile
from briareus_gitlab.repository import GitLabRepositoryClient
from briareus_gitlab.settings import GitLabSettings
from briareus_gitlab.tool_context import GitLabRuntimeContext
from briareus_server.terminal.manager import TerminalError, TerminalManager
from briareus_server.terminal.settings import TerminalSettings
from briareus_server_mount import ServerMountError, project_path, resolve_mount_path
from briareus_workspace.settings import FileSettings
from briareus_workspace.workspace_store import WorkspaceFileStore


class EmptyAccounts:
    def list_accounts(self, *, provider: str) -> AccountList:
        if provider != "github":
            raise AssertionError("Unexpected account provider")
        return AccountList(accounts=[], count=0)


class ServerMountContracts(unittest.IsolatedAsyncioTestCase):
    def test_one_environment_mount_configures_files_terminal_and_provider_factories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            environment = {
                "SERVER_MOUNT_PATH": str(root),
                "FILE_WORKSPACE_ROOT": str(root / "obsolete-files"),
                "TERMINAL_WORKSPACE_ROOT": str(root / "obsolete-terminal"),
            }
            management = cast(ControlPanelClient, EmptyAccounts())
            with patch.dict("os.environ", environment, clear=True):
                settings = (
                    FileSettings(),
                    TerminalSettings(),
                    GitHubPolicySettings(),
                    GitLabSettings(),
                )
                self.assertTrue(all(item.workspace_root == root for item in settings))
                github = GitHubAppClient(public_only=True, auth_type="public")
                gitlab = GitLabApiClient(
                    GitLabProfile(
                        account_id="fixture",
                        alias="fixture",
                        auth_type="private_token",
                        base_url="https://gitlab.example.test",
                    )
                )
                github_factory = GitHubRuntimeContext(
                    management, GitHubPolicySettings(public_allow_anonymous_fallback=True)
                )
                gitlab_factory = GitLabRuntimeContext(management, GitLabSettings())
                self.assertEqual(github.workspace_root, root)
                self.assertEqual(gitlab.workspace_root, root)
                self.assertEqual(github_factory.client("public").workspace_root, root)
                self.assertEqual(gitlab_factory.client("public").workspace_root, root)

    def test_authenticated_github_factory_uses_the_same_mount(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            account = ResolvedAccount(
                id="fixture",
                alias="fixture",
                provider="github",
                auth_type="github_token",
                base_url="https://api.github.com",
                credential="fixture-only-token",
                created_at="",
                updated_at="",
            )
            client = GitHubPrettyIdentityClient.from_account(
                account, GitHubPolicySettings(workspace_root=root)
            )
            self.assertEqual(client.workspace_root, root)

    async def test_terminal_files_browser_download_and_git_destination_share_one_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "mount"
            terminal = TerminalManager(TerminalSettings(workspace_root=root, home=base / "home"))
            files = WorkspaceFileStore(FileSettings(workspace_root=root).workspace_root)
            terminal.workspace_create("example")
            result = await terminal.terminal_exec(
                "example", "printf 'created-by-terminal' > original.txt"
            )
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(
                files.path_for("projects/example/original.txt").read_text(), "created-by-terminal"
            )
            browser_mount = WorkspaceFileStore(root)
            browser_mount.write_text("downloads/browser.txt", "browser-download")
            files.move("downloads/browser.txt", "projects/example/download.txt", overwrite=False)
            checkout = _destination(root, "projects/example/repository")
            checkout.mkdir()
            (checkout / "source.txt").write_text("checkout-source")
            result = await terminal.terminal_exec(
                "example", "cat download.txt repository/source.txt > combined.txt"
            )
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(
                files.path_for("projects/example/combined.txt").read_text(),
                "browser-downloadcheckout-source",
            )
            self.assertFalse((root / "downloads/browser.txt").exists())
            self.assertEqual(project_path(root, "example"), terminal.workspace_path("example"))

    def test_shared_paths_reject_traversal_and_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "mount"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "escape").symlink_to(outside, target_is_directory=True)
            for value in ("../outside/file", "escape/file"):
                with self.assertRaises(ServerMountError):
                    resolve_mount_path(root, value)
                with self.assertRaises(RepositoryCheckoutError):
                    _destination(root, value)
            (root / "projects").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ServerMountError):
                project_path(root, "example")

    def test_local_git_destinations_reject_absolute_paths_with_relative_fix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "mount"
            checkout = root / "projects" / "example" / "repo"
            (checkout / ".git").mkdir(parents=True)
            relative = "projects/example/repo"
            self.assertEqual(checkout_destination(root, relative), checkout)
            github = GitHubPrettyIdentityClient(
                token="fixture", account_id="agent", auth_type="github_token",
                workspace_root=root,
            )
            gitlab = GitLabRepositoryClient(
                GitLabProfile(
                    account_id="fixture",
                    alias="fixture",
                    auth_type="private_token",
                    base_url="https://gitlab.example.test",
                ),
                workspace_root=root,
            )
            self.assertEqual(github._local_git_path(relative), checkout)
            self.assertEqual(gitlab._local_git_path(relative), checkout)
            for absolute in (str(checkout), "/tmp/other/repo"):
                for resolver, error in (
                    (lambda path=absolute: _destination(root, path), RepositoryCheckoutError),
                    (lambda path=absolute: github._local_git_path(path), GitHubAgentError),
                    (lambda path=absolute: gitlab._local_git_path(path), GitLabError),
                ):
                    with (
                        self.subTest(absolute=absolute, error=error),
                        self.assertRaisesRegex(error, "destination must be relative"),
                    ):
                        resolver()
            with self.assertRaisesRegex(RepositoryCheckoutError, "projects/example/repo"):
                checkout_destination(root, str(checkout))
            for destination in ("../outside", "missing"):
                with self.subTest(destination=destination):
                    if destination.startswith("."):
                        with self.assertRaises(RepositoryCheckoutError):
                            checkout_destination(root, destination)
                    else:
                        with self.assertRaisesRegex(GitHubAgentError, "not a Git checkout"):
                            github._local_git_path(destination)

    def test_project_ids_do_not_escape_the_project_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = TerminalManager(TerminalSettings(workspace_root=root, home=root / "home"))
            for value in ("../escape", "nested/name", ".", "..", "/absolute"):
                with self.assertRaises(TerminalError):
                    manager.workspace_path(value)
