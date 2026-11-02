"""Human module preparation and authority continuity after transport decomposition."""

import json
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from control_panel_api._oidc_browser import BrowserCookies
from control_panel_api._resource_broker import ResourceCredentialUnavailable
from control_panel_api.application.human_module import HumanModule, McpInvocation
from control_panel_api.application.module_commands import HumanToolCommand
from control_panel_api.application.module_contracts import (
    McpExchangeResult,
    ModuleRequest,
    ModuleScope,
)
from control_panel_api.application.module_preparation import McpSession, PreparedExchange
from control_panel_api.domain.module_preparation import (
    ModuleInitialization,
    ModuleTarget,
    PreparationEvidence,
)
from control_panel_api.domain.oidc_identity import (
    OidcIdentityRejected,
    OidcSessionStoreUnavailable,
    PrivateOidcResourceCredential,
)
from control_panel_api.domain.panel_protocol import PanelContext
from control_panel_api.domain.platform_authority import PanelOidcSession, ResolvedPlatformUser
from control_panel_api.domain.platform_management import RpcFailure
from control_panel_api.infrastructure.human_module import HttpMcpSession, SocketCredentials
from control_panel_api.infrastructure.module_commands import (
    AnalysisToolCommand,
    BrowserToolCommand,
    FilesToolCommand,
    TerminalToolCommand,
)
from control_panel_api.presentation.human_module import module_request
from control_panel_api.presentation.module_targets import (
    ANALYSIS_TARGET,
    BROWSER_TARGET,
    FILES_TARGET,
    TERMINAL_TARGET,
)
from mcp_types import CallToolResult
from pydantic import JsonValue, SecretStr
from starlette.applications import Starlette
from starlette.types import Message
from starlette.websockets import WebSocket

from runtime_peer.terminal_arguments import JobStartArguments


@dataclass(frozen=True)
class Command:
    tool: str
    preparation_engine: str | None = None
    project_uuid: UUID = field(default_factory=uuid4)
    agent_session_uuid: UUID = field(default_factory=uuid4)
    expected_grant_revision: int = 1
    operation_uuid: UUID = field(default_factory=uuid4)


@dataclass
class SessionFixture:
    evidence: list[PreparationEvidence] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    initialization_ids: list[UUID] = field(default_factory=list)
    initialization_failures: int = 0
    probe_error: RpcFailure | None = None
    reply: CallToolResult = field(default_factory=lambda: CallToolResult(content=[]))

    async def initialize(self, request_id: UUID) -> ModuleInitialization:
        self.calls.append("initialize")
        self.initialization_ids.append(request_id)
        if self.initialization_failures:
            self.initialization_failures -= 1
            raise RpcFailure("TERMINAL_OUTCOME_UNKNOWN", uncertain=True)
        return ModuleInitialization("2025-03-26")

    async def initialized(self) -> None:
        self.calls.append("notifications/initialized")

    async def probe(
        self, request_id: UUID, engine: str | None
    ) -> McpExchangeResult[CallToolResult]:
        del request_id, engine
        self.calls.append("probe")
        if self.probe_error is not None:
            raise self.probe_error
        return McpExchangeResult(self.reply, self.evidence.pop(0))

    async def call(self, command: HumanToolCommand) -> McpExchangeResult[CallToolResult]:
        self.calls.append(command.tool)
        return McpExchangeResult(self.reply, PreparationEvidence())


@dataclass
class SessionsFixture:
    session: SessionFixture

    @asynccontextmanager
    async def open(
        self,
        target: ModuleTarget,
        context: PanelContext,
        command: HumanToolCommand,
        credential: PrivateOidcResourceCredential,
    ) -> AsyncIterator[McpSession[CallToolResult]]:
        del target, context, command, credential
        yield self.session


def context(*, actor: UUID | None = None) -> PanelContext:
    expiry = datetime.now(UTC) + timedelta(minutes=2)
    session = PanelOidcSession("https://issuer", "subject", "panel", expiry)
    proof = ResolvedPlatformUser(
        session.issuer, session.subject, actor or uuid4(), True, "user", expiry, (), ()
    )
    return PanelContext(session, proof)


def credential(proof: PanelContext) -> PrivateOidcResourceCredential:
    return PrivateOidcResourceCredential(
        proof.session.issuer,
        proof.session.subject,
        proof.session.client_id,
        "https://issuer/hands/terminal/mcp",
        proof.session.expires_at,
        SecretStr("unit-resource-token"),
    )


@dataclass
class AuthorityFixture:
    snapshots: list[PanelContext | None]

    async def current(self, project: UUID) -> PanelContext | None:
        del project
        return self.snapshots.pop(0)


@dataclass
class OwnerFixture:
    observations: list[tuple[PanelContext, UUID, ModuleTarget]] = field(default_factory=list)

    async def scope(self, proof: PanelContext, project: UUID, target: ModuleTarget) -> ModuleScope:
        self.observations.append((proof, project, target))
        return ModuleScope(items=())


@dataclass
class CredentialsFixture:
    value: PrivateOidcResourceCredential | None
    calls: list[str] = field(default_factory=list)

    async def resolve(self, module: str) -> PrivateOidcResourceCredential | None:
        self.calls.append(module)
        return self.value


def service(authority: AuthorityFixture, owner: OwnerFixture) -> HumanModule[CallToolResult]:
    return HumanModule(
        authority, owner, CredentialsFixture(None), McpInvocation(SessionsFixture(SessionFixture()))
    )


class PreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_analysis_deadline_never_dispatches_start(self) -> None:
        class Clock:
            current = -11

            def time(self) -> float:
                self.current += 11
                return float(self.current)

        session = SessionFixture([PreparationEvidence(is_error=True, node_preparing=True)])
        with (
            patch(
                "control_panel_api.application.module_preparation.asyncio.get_running_loop",
                return_value=Clock(),
            ),
            self.assertRaises(RpcFailure) as caught,
        ):
            await PreparedExchange(session, ANALYSIS_TARGET).run(
                Command("analysis_start", "radare2")
            )
        self.assertEqual(caught.exception.code, "ANALYSIS_PREPARING")
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(session.calls, ["probe"])

    async def test_analysis_unknown_failure_never_retries_or_starts(self) -> None:
        session = SessionFixture([PreparationEvidence(is_error=True)])
        with self.assertRaises(RpcFailure) as caught:
            await PreparedExchange(session, ANALYSIS_TARGET).run(
                Command("analysis_start", "radare2")
            )
        self.assertEqual(caught.exception.code, "ANALYSIS_PREPARATION_FAILED")
        self.assertEqual(session.calls, ["probe"])

    async def test_analysis_cold_identity_prepares_then_starts_once(self) -> None:
        session = SessionFixture(
            [
                PreparationEvidence(is_error=True, node_preparing=True),
                PreparationEvidence(engine="radare2", tools_ready=True),
            ]
        )
        await PreparedExchange(session, ANALYSIS_TARGET).run(Command("analysis_start", "radare2"))
        self.assertEqual(session.calls, ["probe", "probe", "analysis_start"])

    async def test_terminal_status_returns_ready_probe_without_second_effect(self) -> None:
        session = SessionFixture(
            [
                PreparationEvidence(is_error=True, node_preparing=True),
                PreparationEvidence(workspace_ready=True),
            ]
        )
        result = await PreparedExchange(session, TERMINAL_TARGET).run(Command("terminal_status"))
        self.assertIs(result, session.reply)
        self.assertEqual(session.calls, ["probe", "probe"])

    async def test_cold_initialization_uses_fresh_replay_nonce_without_tools(self) -> None:
        session = SessionFixture(initialization_failures=1)
        result = await PreparedExchange(session, TERMINAL_TARGET).initialize()
        self.assertEqual(result.protocol_version, "2025-03-26")
        self.assertEqual(session.calls, ["initialize", "initialize"])
        self.assertNotEqual(session.initialization_ids[0], session.initialization_ids[1])

    async def test_browser_readonly_preparation_dispatches_mutation_once(self) -> None:
        session = SessionFixture([PreparationEvidence(), PreparationEvidence(running=True)])
        await PreparedExchange(session, BROWSER_TARGET).run(Command("web_operation_start"))
        self.assertEqual(session.calls, ["probe", "probe", "web_operation_start"])

    async def test_pending_status_is_returned_without_waiting_or_dispatching_a_second_effect(
        self,
    ) -> None:
        session = SessionFixture([PreparationEvidence(pending_operation=True)])
        result = await PreparedExchange(session, BROWSER_TARGET).run(
            Command("local_browser_status")
        )
        self.assertIs(result, session.reply)
        self.assertEqual(session.calls, ["probe"])

    async def test_real_browser_probe_error_does_not_spin_until_preparation_deadline(self) -> None:
        session = SessionFixture([PreparationEvidence(is_error=True)])
        with self.assertRaises(RpcFailure) as caught:
            await PreparedExchange(session, BROWSER_TARGET).run(Command("web_operation_start"))
        self.assertEqual(caught.exception.code, "BROWSER_PREPARATION_FAILED")
        self.assertEqual(session.calls, ["probe"])

    async def test_denied_probe_is_never_retried(self) -> None:
        session = SessionFixture(probe_error=RpcFailure("TERMINAL_PERMISSION_DENIED"))
        with self.assertRaises(RpcFailure):
            await PreparedExchange(session, TERMINAL_TARGET).run(Command("workspace_create"))
        self.assertEqual(session.calls, ["probe"])


class AuthorityTests(unittest.IsolatedAsyncioTestCase):
    async def test_scope_binds_current_actor_project_and_terminal_target(self) -> None:
        proof, project, owner = context(), uuid4(), OwnerFixture()
        result = await service(AuthorityFixture([proof, proof]), owner).execute(
            TERMINAL_TARGET, ModuleRequest(project, None)
        )
        self.assertEqual(result, ModuleScope(items=()))
        self.assertEqual(owner.observations, [(proof, project, TERMINAL_TARGET)])

    async def test_fresh_proof_replaces_expired_initial_proof_at_release(self) -> None:
        fresh = context()
        old = replace(
            fresh, proof=replace(fresh.proof, expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        owner = OwnerFixture()
        result = await service(AuthorityFixture([old, fresh]), owner).execute(
            BROWSER_TARGET, ModuleRequest(uuid4(), None)
        )
        self.assertEqual(result, ModuleScope(items=()))

    async def test_unauthenticated_request_never_reads_owner(self) -> None:
        owner = OwnerFixture()
        with self.assertRaises(RpcFailure):
            await service(AuthorityFixture([None]), owner).execute(
                BROWSER_TARGET, ModuleRequest(uuid4(), None)
            )
        self.assertFalse(owner.observations)

    async def test_revoked_or_changed_actor_withholds_owner_reply(self) -> None:
        initial = context()
        for fresh in (None, context()):
            with self.subTest(fresh=fresh):
                owner = OwnerFixture()
                with self.assertRaises(RpcFailure) as caught:
                    await service(AuthorityFixture([initial, fresh]), owner).execute(
                        BROWSER_TARGET, ModuleRequest(uuid4(), None)
                    )
                self.assertEqual(caught.exception.code, "BROWSER_CURRENT_AUTHORITY_REQUIRED")
                self.assertEqual(len(owner.observations), 1)


def ingress(target: ModuleTarget, tool: str, arguments: JsonValue) -> ModuleRequest:
    return module_request(
        target.prefix + ".command",
        {
            "project_uuid": str(uuid4()),
            "operation_uuid": str(uuid4()),
            "tool": tool,
            "arguments": arguments,
        },
        target,
    )


class IngressTests(unittest.TestCase):
    def test_terminal_rejects_browser_and_unexposed_tools(self) -> None:
        for tool in ("local_browser_open", "workspace_delete", "terminal_exec"):
            with self.subTest(tool=tool), self.assertRaises(RpcFailure):
                ingress(TERMINAL_TARGET, tool, {})

    def test_terminal_accepts_existing_typed_project_tools(self) -> None:
        cases: tuple[tuple[str, JsonValue], ...] = (
            ("job_list", {"workspace_id": "default", "offset": 0, "limit": 50}),
            ("job_write", {"job_id": "a" * 32, "data": "hello\n"}),
            ("job_resize", {"job_id": "a" * 32, "cols": 100, "rows": 30}),
            ("workspace_info", {"workspace_id": "default"}),
        )
        for tool, arguments in cases:
            with self.subTest(tool=tool):
                request = ingress(TERMINAL_TARGET, tool, arguments)
                self.assertIsNotNone(request.command)
                if request.command is not None:
                    self.assertEqual(request.command.tool, tool)

    def test_terminal_history_uses_readonly_preparation(self) -> None:
        self.assertTrue(TERMINAL_TARGET.prepares("job_list", None))
        self.assertFalse(TERMINAL_TARGET.prepares("job_write", None))
        self.assertFalse(TERMINAL_TARGET.prepares("job_resize", None))

    def test_direct_and_nested_devtools_are_rejected(self) -> None:
        cases: tuple[tuple[str, JsonValue], ...] = (
            ("local_devtools_evaluate", {}),
            ("web_operation_start", {"tool": "local_devtools_evaluate", "arguments": {}}),
        )
        for tool, arguments in cases:
            with self.subTest(tool=tool), self.assertRaises(RpcFailure):
                ingress(BROWSER_TARGET, tool, arguments)


@dataclass
class FailedEscrow:
    error: Exception

    async def resolve(self, ticket: str, module: str) -> PrivateOidcResourceCredential | None:
        del ticket, module
        raise self.error


async def unused_receive() -> Message:
    raise AssertionError("Credential lookup must not read WebSocket frames")


async def unused_send(message: Message) -> None:
    del message
    raise AssertionError("Credential lookup must not send WebSocket frames")


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_resource_escrow_failures_are_bounded_rpc_errors(self) -> None:
        for error, code in (
            (ResourceCredentialUnavailable(), "BROWSER_CREDENTIAL_UNAVAILABLE"),
            (OidcSessionStoreUnavailable(), "BROWSER_CREDENTIAL_UNAVAILABLE"),
            (OidcIdentityRejected(), "BROWSER_SIGN_IN_REQUIRED"),
        ):
            app = Starlette()
            app.state.resource_credentials = FailedEscrow(error)
            socket = WebSocket(
                {"type": "websocket", "app": app, "headers": [], "path": "/"},
                unused_receive,
                unused_send,
            )
            with (
                patch(
                    "control_panel_api.infrastructure.human_module._strict_browser_cookies",
                    return_value=BrowserCookies(session="ticket"),
                ),
                self.assertRaises(RpcFailure) as caught,
            ):
                await SocketCredentials(socket, prefix="browser").resolve("web")
            self.assertEqual(caught.exception.code, code)

    async def test_lost_terminal_reply_is_uncertain_and_never_replayed(self) -> None:
        calls: list[str] = []

        def transport(request: httpx.Request) -> httpx.Response:
            frame = json.loads(request.content)
            calls.append(frame["method"])
            if frame["method"] == "tools/call":
                self.assertIsNone(request.extensions["timeout"]["read"])
                raise httpx.ReadTimeout("Lost reply", request=request)
            if "id" not in frame:
                return httpx.Response(202)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": frame["id"],
                    "result": {"protocolVersion": "2025-03-26"},
                },
            )

        proof = context()
        command = TerminalToolCommand(
            project_uuid=uuid4(),
            operation_uuid=uuid4(),
            tool="job_start",
            arguments=JobStartArguments(workspace_id="owned", command="fixture"),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:

            class Permits:
                async def issue(
                    self,
                    *,
                    project_uuid: UUID,
                    request_uuid: UUID,
                    body: bytes,
                    credential: PrivateOidcResourceCredential,
                    module: str = "web",
                ) -> str:
                    assert module == "terminal"
                    assert project_uuid == command.project_uuid
                    assert request_uuid.version == 4
                    assert body
                    assert credential.bearer.get_secret_value() == "unit-resource-token"
                    return "signed-human-terminal-fixture"

            session = HttpMcpSession(
                client, TERMINAL_TARGET, proof, command, credential(proof), Permits()
            )
            prepared = PreparedExchange(session, TERMINAL_TARGET)
            await prepared.initialize()
            await session.initialized()
            with self.assertRaises(RpcFailure) as caught:
                await prepared.run(command)
        self.assertEqual(caught.exception.code, "TERMINAL_OUTCOME_UNKNOWN")
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(calls, ["initialize", "notifications/initialized", "tools/call"])

    async def test_human_browser_binds_exact_bytes_without_agent_headers(self) -> None:
        bodies: list[bytes] = []
        proof = context()
        project = uuid4()

        class Permits:
            async def issue(
                self,
                *,
                project_uuid: UUID,
                request_uuid: UUID,
                body: bytes,
                credential: PrivateOidcResourceCredential,
                module: str = "web",
            ) -> str:
                assert module in {"web", "files", "terminal", "reverse"}
                assert project_uuid == project and request_uuid.version == 4
                assert credential.bearer.get_secret_value() == "unit-resource-token"
                bodies.append(body)
                return "signed-human-fixture"

        def transport(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.content, bodies[-1])
            self.assertEqual(request.headers["x-briareus-human-permit"], "signed-human-fixture")
            self.assertNotIn("x-briareus-agent-session-uuid", request.headers)
            self.assertNotIn("x-briareus-grant-revision", request.headers)
            self.assertEqual(request.headers["authorization"], "Bearer unit-resource-token")
            frame = json.loads(request.content)
            if "id" not in frame:
                return httpx.Response(202)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": frame["id"],
                    "result": {"protocolVersion": "2025-03-26"},
                },
            )

        for target, schema, tool in (
            (BROWSER_TARGET, BrowserToolCommand, "local_browser_status"),
            (FILES_TARGET, FilesToolCommand, "file_status"),
            (TERMINAL_TARGET, TerminalToolCommand, "terminal_status"),
            (ANALYSIS_TARGET, AnalysisToolCommand, "analysis_poll"),
        ):
            with self.subTest(module=target.module):
                command = schema.model_validate(
                    {
                        "project_uuid": project,
                        "operation_uuid": uuid4(),
                        "tool": tool,
                        "arguments": {"operation_id": "request:" + str(uuid4())}
                        if target.module == "reverse"
                        else {},
                    }
                )
                resource = replace(
                    credential(proof), audience=f"https://127.0.0.1/hands/{target.module}/mcp"
                )
                async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
                    session = HttpMcpSession(client, target, proof, command, resource, Permits())
                    await session.initialize(uuid4())
                    await session.initialized()
        self.assertEqual(len(bodies), 8)

    def test_validated_pending_metadata_survives_the_browser_codec(self) -> None:
        from control_panel_api.infrastructure.module_codec import decode_mcp_reply

        decoded = decode_mcp_reply(
            {
                "content": [],
                "structuredContent": {
                    "result": {
                        "running": False,
                        "starting": True,
                        "cdp_reachable": False,
                        "pending": {
                            "operation_id": f"{uuid4()}:{uuid4()}",
                            "tool": "local_browser_open",
                        },
                    }
                },
            },
            module="web",
            tool="local_browser_status",
        )
        self.assertTrue(decoded.evidence.pending_operation)
        self.assertFalse(decoded.evidence.running)
