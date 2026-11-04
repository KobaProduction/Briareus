from __future__ import annotations

import base64
import hashlib
import http.client
import json
import tempfile
import unittest
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import cast
from unittest.mock import patch

from briareus_analysis.settings import AnalysisSettings
from briareus_analysis.workspace_transfer import AnalysisTransferError, AnalysisWorkspaceTransfers
from briareus_cache.cache import SharedCache
from briareus_cache.settings import ValkeySettings
from briareus_control_panel_client.control_panel_client import (
    ControlPanelClient,
    ControlPanelClientError,
)
from briareus_control_panel_client.settings import ControlPanelClientSettings
from briareus_github.github_agent import GitHubAgentError
from briareus_github.github_identity import GitHubPrettyIdentityClient
from briareus_gitlab.errors import GitLabError
from briareus_gitlab.repository import GitLabRepositoryClient
from briareus_http_transport.http_transport import PooledHttpTransport
from briareus_invocation_events import InvocationEvent
from briareus_json_values import JsonObject, JsonValue
from briareus_telemetry.observability import _otlp_bearer_headers, _resource_attributes
from briareus_telemetry.settings import ObservabilitySettings
from briareus_workspace.workspace_store import WorkspaceFileError, WorkspaceFileStore
from control_panel_api.realtime import RealtimeBus


class ValkeyCredentialContracts(unittest.TestCase):
    def test_missing_password_and_embedded_url_credentials_are_rejected(self) -> None:
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(ValueError):
            ValkeySettings()
        with self.assertRaisesRegex(ValueError, "VALKEY_URL owns topology only") as raised:
            ValkeySettings(url="redis://user:must-stay-private@valkey:6379/0", password="other")
        self.assertNotIn("must-stay-private", str(raised.exception))

    def test_cache_and_realtime_clients_use_exact_separate_credentials(self) -> None:
        settings = ValkeySettings(username="briareus-service", password=" exact secret= @ ")
        cache = SharedCache(settings)
        realtime = RealtimeBus(cache, settings)
        try:
            for client in (cache._client, realtime._redis):
                options = client.connection_pool.connection_kwargs
                self.assertEqual(options["username"], "briareus-service")
                self.assertEqual(options["password"], " exact secret= @ ")
                self.assertEqual(options["host"], "valkey")
        finally:
            cache._client.connection_pool.close()
            realtime._redis.connection_pool.close()


class UnusedCache:
    def key(self, *parts: str) -> str:
        return ":".join(parts)

    def get_json(self, key: str) -> JsonValue | None:
        del key
        return None

    def set_json(self, key: str, value: object, *, ttl_seconds: int) -> bool:
        del key, value, ttl_seconds
        return False

    def delete(self, *_keys: str) -> bool:
        return False


@dataclass(frozen=True)
class WireRequest:
    method: str
    target: str
    body: bytes | None


class Response:
    status = 204
    will_close = False
    headers = Message()

    def read(self) -> bytes:
        return b""


class Connection:
    def __init__(self, fail: bool) -> None:
        self.fail = fail
        self.closed = False
        self.requests: list[WireRequest] = []

    def request(
        self,
        method: str,
        target: str,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        del headers
        self.requests.append(WireRequest(method, target, body))
        if self.fail:
            raise BrokenPipeError("test closed connection")

    def getresponse(self) -> http.client.HTTPResponse:
        return cast(http.client.HTTPResponse, Response())

    def close(self) -> None:
        self.closed = True


class Connections:
    def __init__(self) -> None:
        self.opened: list[Connection] = []
        self.fail = False

    def open(self) -> http.client.HTTPConnection:
        connection = Connection(self.fail)
        self.opened.append(connection)
        return cast(http.client.HTTPConnection, connection)


class AuditAndTelemetryContracts(unittest.TestCase):
    def client(self, connections: Connections) -> ControlPanelClient:
        client = ControlPanelClient(
            ControlPanelClientSettings(
                url="http://panel.internal", service_token="test-service-token"
            ),
            cache=UnusedCache(),
        )
        client._transport = PooledHttpTransport(connections.open)
        return client

    def test_audit_writes_use_fresh_connections_without_consuming_the_read_pool(self) -> None:
        connections = Connections()
        client = self.client(connections)
        client._transport.request("GET", "/health")
        event = InvocationEvent(
            module="web", tool="browser_status", status="success", duration_ms=1
        )
        client.record_invocations([event])
        client.record_invocations([event])
        self.assertEqual(len(connections.opened), 3)
        self.assertFalse(connections.opened[0].closed)
        self.assertTrue(all(item.closed for item in connections.opened[1:]))
        observed = connections.opened[1].requests[0]
        self.assertEqual((observed.method, observed.target), ("POST", "/internal/events/batch"))
        assert observed.body is not None
        self.assertEqual(json.loads(observed.body)["events"][0]["tool"], "browser_status")

    def test_failed_audit_is_not_replayed_and_empty_batches_have_no_effect(self) -> None:
        connections = Connections()
        client = self.client(connections)
        client.record_invocations([])
        self.assertEqual(connections.opened, [])
        connections.fail = True
        with self.assertRaises(ControlPanelClientError):
            client.record_invocations(
                [
                    InvocationEvent(
                        module="web", tool="browser_status", status="error", duration_ms=1
                    ),
                ]
            )
        self.assertEqual(len(connections.opened), 1)
        self.assertEqual(len(connections.opened[0].requests), 1)
        self.assertTrue(connections.opened[0].closed)

    def test_otlp_uses_separate_optional_bearer_secret_and_canonical_signal_paths(self) -> None:
        settings = ObservabilitySettings(
            environment="test", endpoint="https://collector.example.test/", bearer_token="test-only"
        )
        self.assertEqual(_otlp_bearer_headers(settings), {"Authorization": "Bearer test-only"})
        for signal in ("logs", "traces", "metrics"):
            self.assertEqual(
                settings.signal_endpoint(signal), "https://collector.example.test/v1/" + signal
            )
        with (
            patch.dict(
                "os.environ", {"OTEL_EXPORTER_OTLP_HEADERS": "Authorization=legacy"}, clear=True
            ),
        ):
            self.assertEqual(
                _otlp_bearer_headers(
                    ObservabilitySettings(
                        environment="test", endpoint="https://collector.example.test"
                    )
                ),
                {},
            )

    def test_deployment_identity_and_canonical_operator_keys_reach_otel_resources(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "DEPLOYMENT_ENVIRONMENT": "staging",
                "OTEL_NAMESPACE": "briareus-v1",
                "OTEL_SERVICE_NAME": "briareus-files",
                "OTEL_ENDPOINT": "https://collector.example.test",
                "OTEL_BEARER_TOKEN": "test-only",
            },
            clear=True,
        ):
            settings = ObservabilitySettings()
        attributes = _resource_attributes(settings, "files")
        self.assertEqual(attributes["deployment.environment.name"], "staging")
        self.assertEqual(attributes["service.namespace"], "briareus-v1")
        self.assertEqual(attributes["service.name"], "briareus-files")
        self.assertEqual(settings.endpoint, "https://collector.example.test")
        self.assertEqual(_otlp_bearer_headers(settings), {"Authorization": "Bearer test-only"})
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(ValueError):
            ObservabilitySettings()
        with self.assertRaises(ValueError):
            ObservabilitySettings(environment="")


@dataclass(frozen=True)
class GitProfile:
    profile_id: str = "test-account"


class GitWorkspace:
    public_only = False
    anonymous_only = False
    account_id = "test-account"
    profile = GitProfile()
    protected_branches: frozenset[str] = frozenset()

    def __init__(self, root: Path, authorized: bool = True) -> None:
        self.workspace_root = root
        self.checkout = root / "checkout"
        self.authorized = authorized
        self.commands: list[tuple[str, ...]] = []

    @staticmethod
    def _assert_allowed(repository: str) -> str:
        return repository

    def _local_git_path(self, _destination: str) -> Path:
        return self.checkout

    def _git_optional_output(self, _path: Path, *args: str) -> str:
        name = args[-1]
        if name.endswith("transportAuthorized"):
            return "true" if self.authorized else "false"
        if name.endswith("accountId"):
            return self.account_id
        return "team/repository"

    def _git_output(self, _path: Path, *args: str) -> str:
        self.commands.append(args)
        return "v1" if args[0] == "branch" else "a" * 40

    def _assert_branch_mutation_allowed(self, _repository: str, branch: str) -> str:
        if branch in self.protected_branches:
            raise GitHubAgentError("protected branch")
        return branch


class ProviderWorkspaceAuthorityContracts(unittest.TestCase):
    def test_both_git_providers_preserve_custom_hooks_and_require_explicit_workspace_authority(
        self,
    ) -> None:
        for provider in ("github", "gitlab"):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as directory:
                workspace = GitWorkspace(Path(directory))
                hook = workspace.checkout / ".git/hooks/pre-push"
                hook.parent.mkdir(parents=True)
                hook.write_text("#!/bin/sh\n# custom owner hook\nexit 0\n")
                original = hook.read_bytes()
                self.push(provider, workspace)
                self.assertEqual(hook.read_bytes(), original)
                self.assertTrue(any(command[0] == "push" for command in workspace.commands))
                workspace.authorized = False
                workspace.commands.clear()
                with self.assertRaises((GitHubAgentError, GitLabError)):
                    self.push(provider, workspace)
                self.assertFalse(any(command[0] == "push" for command in workspace.commands))

    @staticmethod
    def push(provider: str, workspace: GitWorkspace) -> None:
        if provider == "github":
            result = GitHubPrettyIdentityClient.push_local_git(
                cast(GitHubPrettyIdentityClient, workspace),
                "team/repository",
                "checkout",
            )
        else:
            result = GitLabRepositoryClient.push_local_git(
                cast(GitLabRepositoryClient, workspace),
                "team/repository",
                "checkout",
            )
        if result["pushed"] is not True:
            raise AssertionError("Expected the authorized workspace to be pushed")

    def test_private_workspace_files_reject_traversal_and_symlink_escapes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            outside = root / "private"
            workspace.mkdir()
            outside.mkdir()
            (outside / "secret.txt").write_text("must-stay-private")
            (workspace / "escape").symlink_to(outside, target_is_directory=True)
            files = WorkspaceFileStore(workspace)
            for path in ("../private/secret.txt", "escape/secret.txt", str(outside / "secret.txt")):
                with self.subTest(path=path), self.assertRaises(WorkspaceFileError):
                    files.read(path)
            self.assertEqual((outside / "secret.txt").read_text(), "must-stay-private")


class TransferBackend(AnalysisWorkspaceTransfers):
    def __init__(self, root: Path, fail_write: bool = False) -> None:
        super().__init__(
            AnalysisSettings(direct_upload_url=""),
            WorkspaceFileStore(root),
            max_file_bytes=1024,
            chunk_bytes=3,
        )
        self.fail_write = fail_write
        self.tools: list[str] = []
        self.projects: list[str] = []
        self.content = bytearray()

    async def _call(self, name: str, arguments: JsonObject) -> JsonObject:
        self.tools.append(name)
        self.projects.append(str(arguments.get("project_id", "")))
        if name == "artifact_stage_begin":
            return {"stage_id": "stage-A"}
        if name == "artifact_stage_write":
            if self.fail_write:
                raise AnalysisTransferError("transfer interrupted")
            self.content.extend(base64.b64decode(str(arguments["data_base64"])))
            return {"next_offset": len(self.content)}
        if name == "artifact_stage_finish":
            return {"path": "/backend/artifact.bin"}
        if name == "artifact_stage_cancel":
            return {}
        raise AssertionError("Unexpected backend operation: " + name)


class AnalysisTransferIntegrityContracts(unittest.IsolatedAsyncioTestCase):
    async def test_staged_transfer_preserves_bytes_integrity_and_project_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = b"Briareus-artifact-content"
            (root / "artifact.bin").write_bytes(content)
            transfer = TransferBackend(root)
            result = await transfer._transfer_workspace_file("project-A", "artifact.bin")
            self.assertEqual(bytes(transfer.content), content)
            self.assertEqual(result["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(result["size_bytes"], len(content))
            self.assertEqual(result["transfer_method"], "mcp_base64")
            self.assertEqual(transfer.tools[-1], "artifact_stage_finish")
            self.assertTrue(transfer.projects)
            self.assertEqual(set(transfer.projects), {"project-A"})

    async def test_failed_stage_cancels_the_remote_stage_without_deleting_the_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "artifact.bin"
            source.write_bytes(b"keep-source")
            transfer = TransferBackend(root, fail_write=True)
            with self.assertRaises(AnalysisTransferError):
                await transfer._transfer_workspace_file("project-A", "artifact.bin")
            self.assertEqual(transfer.tools[-1], "artifact_stage_cancel")
            self.assertEqual(source.read_bytes(), b"keep-source")
