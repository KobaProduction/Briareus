"""Current socket proof, resource owner and public MCP HTTP transport adapters."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID, uuid4

import httpx
from fastapi import WebSocket
from fastapi.responses import JSONResponse
from mcp_types import (
    CallToolRequestParams,
    ClientCapabilities,
    Implementation,
    InitializeRequestParams,
)

from control_panel_api._oidc import RauthyOidcAdapter
from control_panel_api._oidc_browser import _SID_COOKIE, _strict_browser_cookies
from control_panel_api._oidc_membership import CurrentPlatformContext
from control_panel_api._oidc_origin_policy import PUBLIC_ORIGIN
from control_panel_api._resource_broker import ResourceCredentialUnavailable
from control_panel_api.application.human_web import HumanEffectPermits
from control_panel_api.application.module_commands import HumanToolCommand
from control_panel_api.application.module_contracts import (
    McpExchangeResult,
    ModuleScope,
)
from control_panel_api.domain.module_preparation import ModuleInitialization, ModuleTarget
from control_panel_api.domain.oidc_identity import (
    OidcIdentityRejected,
    OidcSessionStoreUnavailable,
    PrivateOidcResourceCredential,
)
from control_panel_api.domain.panel_protocol import PanelContext
from control_panel_api.domain.platform_management import RpcFailure
from runtime_peer import PeerClient
from runtime_peer.response_decoding import successful_reply

from .module_call_encoding import tool_parameters
from .module_codec import decode_initialization, decode_mcp_reply
from .module_commands import (
    AnalysisToolCommand,
    BrowserToolCommand,
    FilesToolCommand,
    NativeToolCommand,
    TerminalToolCommand,
)
from .module_replies import NativeToolReply

LOG = logging.getLogger(__name__)


class SocketModuleAuthority:
    def __init__(self, socket: WebSocket, context: CurrentPlatformContext) -> None:
        self._socket = socket
        self._context = context

    async def current(self, project: UUID) -> PanelContext | None:
        value = await self._context(self._socket, project)
        return None if isinstance(value, JSONResponse) else PanelContext(*value)


class ModuleScopes:
    def __init__(self, resources: PeerClient) -> None:
        self._resources = resources

    async def scope(
        self, context: PanelContext, project: UUID, target: ModuleTarget
    ) -> ModuleScope:
        _owner_reply = await self._resources.call(
            "/internal/v1/resources/" + target.prefix + "-scope",
            {
                "issuer": context.proof.issuer,
                "subject": context.proof.subject,
                "actor_uuid": str(context.proof.user_uuid),
                "project_uuid": str(project),
                "identity_expires_at": min(
                    context.session.expires_at, context.proof.expires_at
                ).isoformat(),
            },
            decode=successful_reply(ModuleScope.model_validate),
        )
        status, reply = _owner_reply.status, _owner_reply.body
        if status != 200 or reply is None:
            raise RpcFailure(target.prefix.upper() + "_SCOPE_UNAVAILABLE")
        return reply


@runtime_checkable
class ResourceEscrow(Protocol):
    async def resolve(self, ticket: str, module: str) -> PrivateOidcResourceCredential | None: ...


@runtime_checkable
class ProviderResourceEscrow(ResourceEscrow, Protocol):
    provider: RauthyOidcAdapter


class SocketCredentials:
    def __init__(self, socket: WebSocket, *, prefix: str) -> None:
        self._socket = socket
        self._prefix = prefix.upper()

    def _escrow(self) -> ResourceEscrow:
        escrow = getattr(self._socket.app.state, "resource_credentials", None)
        if not isinstance(escrow, ResourceEscrow):
            raise RpcFailure(self._prefix + "_CREDENTIAL_UNAVAILABLE")
        return escrow

    async def resolve(self, module: str) -> PrivateOidcResourceCredential | None:
        escrow = self._escrow()
        cookies = _strict_browser_cookies(self._socket)
        ticket = cookies.get(_SID_COOKIE) if cookies else None
        if ticket is None:
            raise RpcFailure(self._prefix + "_CREDENTIAL_UNAVAILABLE")
        try:
            return await escrow.resolve(ticket, module)
        except OidcIdentityRejected:
            raise RpcFailure(self._prefix + "_SIGN_IN_REQUIRED") from None
        except (ResourceCredentialUnavailable, OidcSessionStoreUnavailable):
            raise RpcFailure(self._prefix + "_CREDENTIAL_UNAVAILABLE") from None

    def human_permits(self) -> HumanEffectPermits:
        issuer = getattr(self._socket.app.state, "human_web_permits", None)
        if not isinstance(issuer, HumanEffectPermits):
            raise RpcFailure("BROWSER_AUTHORITY_UNAVAILABLE")
        return issuer

    def client(self) -> httpx.AsyncClient:
        escrow = self._escrow()
        if not isinstance(escrow, ProviderResourceEscrow):
            raise RpcFailure(self._prefix + "_CREDENTIAL_UNAVAILABLE")
        return escrow.provider._client


def _safe_reply_code(raw: bytes) -> str:
    try:
        value = json.loads(raw)
    except ValueError:
        return "UNAVAILABLE"
    code = value.get("code") if isinstance(value, dict) else None
    return (
        code
        if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", code)
        else "UNAVAILABLE"
    )


def _decode_reply[ReplyT](
    raw: str,
    request_id: str,
    decode: Callable[[object], ReplyT],
    *,
    streaming: bool,
) -> ReplyT:
    value: object = None
    if streaming:
        entries = [
            json.loads(line[5:].strip()) for line in raw.splitlines() if line.startswith("data:")
        ]
        value = next(
            (item for item in entries if isinstance(item, dict) and item.get("id") == request_id),
            None,
        )
    else:
        value = json.loads(raw)
    if not isinstance(value, dict) or value.get("id") != request_id or "error" in value:
        raise ValueError("Unexpected MCP response envelope")
    return decode(value["result"])


def _human_target(command: NativeToolCommand) -> Literal["web", "files", "terminal", "reverse"]:
    if isinstance(command, BrowserToolCommand):
        return "web"
    if isinstance(command, FilesToolCommand):
        return "files"
    if isinstance(command, TerminalToolCommand):
        return "terminal"
    if isinstance(command, AnalysisToolCommand):
        return "reverse"
    raise RpcFailure("HUMAN_AUTHORITY_UNAVAILABLE")


class HttpMcpSession:
    def __init__(
        self,
        client: httpx.AsyncClient,
        target: ModuleTarget,
        context: PanelContext,
        command: NativeToolCommand,
        credential: PrivateOidcResourceCredential,
        human_permits: HumanEffectPermits | None = None,
    ) -> None:
        self._credential, self._human_permits = credential, human_permits
        self._client, self._target, self._context, self._command = client, target, context, command
        self._endpoint = PUBLIC_ORIGIN + "/hands/" + target.module + "/mcp"
        self._headers = {
            "Authorization": "Bearer " + credential.bearer.get_secret_value(),
            "X-Briareus-Project-UUID": str(command.project_uuid),
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-03-26",
        }
        module = _human_target(command)
        if target.module != module or human_permits is None:
            raise RpcFailure(target.prefix.upper() + "_AUTHORITY_UNAVAILABLE")

    async def _request_headers(self, request_uuid: UUID, body: bytes) -> httpx.Headers:
        headers = httpx.Headers(self._headers)
        if self._human_permits is not None:
            headers["X-Briareus-Human-Permit"] = await self._human_permits.issue(
                project_uuid=self._command.project_uuid,
                request_uuid=request_uuid,
                body=body,
                credential=self._credential,
                module=_human_target(self._command),
            )
        return headers

    def _denied(self, method: str, status: int, raw: bytes) -> RpcFailure:
        LOG.warning(
            "Human MCP response unavailable module=%s method=%s status=%s code=%s "
            "actor=%s project=%s authority=%s",
            self._target.module,
            method,
            status,
            _safe_reply_code(raw),
            self._context.proof.user_uuid,
            self._command.project_uuid,
            "human",
        )
        code = "_PERMISSION_DENIED" if status in {401, 403} else "_OUTCOME_UNKNOWN"
        return RpcFailure(self._target.prefix.upper() + code, uncertain=True)

    async def _exchange[ReplyT](
        self,
        request_id: str,
        method: str,
        parameters: InitializeRequestParams | CallToolRequestParams,
        decode: Callable[[object], ReplyT],
    ) -> ReplyT:
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": parameters.model_dump(mode="json", by_alias=True, exclude_unset=True),
            },
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
        headers = await self._request_headers(UUID(request_id), payload)
        try:
            async with self._client.stream(
                "POST",
                self._endpoint,
                headers=headers,
                content=payload,
                timeout=httpx.Timeout(15, read=None),
            ) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 1048576:
                        raise RpcFailure(self._target.prefix.upper() + "_REPLY_TOO_LARGE")
                if response.status_code != 200:
                    raise self._denied(method, response.status_code, bytes(body))
                if response.headers.get("mcp-session-id"):
                    self._headers["MCP-Session-Id"] = response.headers["mcp-session-id"]
                return _decode_reply(
                    bytes(body).decode(),
                    request_id,
                    decode,
                    streaming="text/event-stream" in response.headers.get("content-type", ""),
                )
        except (httpx.HTTPError, ValueError, KeyError, UnicodeError):
            raise RpcFailure(
                self._target.prefix.upper() + "_OUTCOME_UNKNOWN", uncertain=True
            ) from None

    async def initialize(self, request_id: UUID) -> ModuleInitialization:
        return await self._exchange(
            str(request_id),
            "initialize",
            InitializeRequestParams(
                protocol_version="2025-03-26",
                capabilities=ClientCapabilities(),
                client_info=Implementation(
                    name="briareus-human-" + self._target.prefix, version="1"
                ),
            ),
            decode_initialization,
        )

    async def probe(
        self, request_id: UUID, engine: str | None
    ) -> McpExchangeResult[NativeToolReply]:
        return await self._exchange(
            str(request_id),
            "tools/call",
            CallToolRequestParams(
                name=self._target.status_tool, arguments={"engine": engine} if engine else {}
            ),
            lambda value: decode_mcp_reply(
                value, module=self._target.module, tool=self._target.status_tool
            ),
        )

    async def call(self, command: HumanToolCommand) -> McpExchangeResult[NativeToolReply]:
        if command is not self._command:
            raise RpcFailure(self._target.prefix.upper() + "_COMMAND_INVALID")
        return await self._exchange(
            str(command.operation_uuid),
            "tools/call",
            tool_parameters(self._command),
            lambda value: decode_mcp_reply(value, module=self._target.module, tool=command.tool),
        )

    async def initialized(self) -> None:
        body = b'{"jsonrpc":"2.0","method":"notifications/initialized"}'
        headers = await self._request_headers(uuid4(), body)
        try:
            response = await self._client.post(
                self._endpoint,
                headers=headers,
                content=body,
            )
        except httpx.HTTPError:
            raise RpcFailure(self._target.prefix.upper() + "_INITIALIZATION_REQUIRED") from None
        if response.status_code not in {200, 202, 204}:
            raise RpcFailure(self._target.prefix.upper() + "_INITIALIZATION_REQUIRED")


class HumanMcpSessions:
    def __init__(self, credentials: SocketCredentials) -> None:
        self._credentials = credentials

    @asynccontextmanager
    async def open(
        self,
        target: ModuleTarget,
        context: PanelContext,
        command: HumanToolCommand,
        credential: PrivateOidcResourceCredential,
    ) -> AsyncIterator[HttpMcpSession]:
        if not isinstance(
            command,
            (TerminalToolCommand, FilesToolCommand, BrowserToolCommand, AnalysisToolCommand),
        ):
            raise RpcFailure(target.prefix.upper() + "_COMMAND_INVALID")
        yield HttpMcpSession(
            self._credentials.client(),
            target,
            context,
            command,
            credential,
            self._credentials.human_permits(),
        )
