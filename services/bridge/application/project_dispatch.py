"""Unmounted Briareus Project dispatch, signed A6 actions only.

C1-B/C2 must provide a verified principal/session/grants transport and typed
backend identity. This is a private composition root, NOT a public MCP tool.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID, uuid4

from bridge.domain.project_dispatch import (
    ProjectGatewayDispatchUnavailable as ProjectGatewayDispatchUnavailable,
)
from bridge.domain.project_dispatch import checked_request_uuid
from modules.project_runtime import (
    ProjectAction,
    ProjectInvocation,
    ProjectOperationScope,
    ProjectPermit,
)

from .owner_readiness import (
    ProjectOwnerReadinessPort as ProjectOwnerReadinessPort,
)
from .owner_readiness import (
    ProjectOwnerReleaseManifestPort as ProjectOwnerReleaseManifestPort,
)
from .owner_readiness import (
    RequireOwnerReadiness,
)
from .project_contracts import (
    FileList,
    FilePath,
    FileRead,
    FileUpload,
    FileWriteStatus,
    ProjectCommand,
    ProjectResult,
    ResourceSelection,
)


# C2-UNMOUNTED source registry; operation cannot be selected by untrusted
# MCP arguments or by an accidentally permissive classifier implementation.
# Exactly one bounded mutation is staged: Files upload under A6 signed quota.
@dataclass(frozen=True, slots=True)
class ProjectTool:
    action: ProjectAction
    command_type: type[ProjectCommand]


_PRIVATE_TOOLS: dict[tuple[str, str], ProjectTool] = {
    ("files", "list"): ProjectTool("files.read", FileList),
    ("files", "info"): ProjectTool("files.read", FilePath),
    ("files", "read_base64"): ProjectTool("files.read", FileRead),
    ("files", "sha256"): ProjectTool("files.read", FilePath),
    ("files", "upload_base64"): ProjectTool("files.write", FileUpload),
    ("files", "write_status"): ProjectTool("files.write", FileWriteStatus),
    ("github", "connections"): ProjectTool("svc.read", ResourceSelection),
    ("gitlab", "connections"): ProjectTool("svc.read", ResourceSelection),
    ("observability", "connections"): ProjectTool("infrastructure.read", ResourceSelection),
    ("variables", "metadata"): ProjectTool("resources.use", ResourceSelection),
}
_PRIVATE_TOOL_ACTIONS = {selector: tool.action for selector, tool in _PRIVATE_TOOLS.items()}
_MUTATING_ACTIONS: frozenset[ProjectAction] = frozenset(
    {
        "files.write",
        "files.manage",
        "terminal.attach",
        "web.internal",
        "web.remote",
        "reverse.import",
        "svc.write",
    }
)


class ProjectToolClassifier(Protocol):
    async def classify(self, backend: str, tool: str) -> ProjectAction | None: ...


class ProjectDispatchAuthority(Protocol):
    async def require(
        self, invocation: ProjectInvocation, action: ProjectAction
    ) -> ProjectPermit: ...


@dataclass(frozen=True, slots=True)
class AuthorizedToolForward:
    backend: str
    tool: str
    arguments: ProjectCommand
    permit: ProjectPermit
    request_uuid: UUID
    invocation: ProjectInvocation


class AuthenticatedProjectForwarder(Protocol):
    def fingerprint(
        self,
        invocation: ProjectInvocation,
        action: ProjectAction,
        request_uuid: UUID,
        backend: str,
        tool: str,
        command: ProjectCommand,
    ) -> str: ...

    async def forward(self, request: AuthorizedToolForward) -> ProjectResult: ...


class ProjectGatewayDispatch:
    """A private allowlisted entry requiring real per-call Project authorization.

    Upstream service must independently validate service identity and its
    actor/Project context. A Python permit alone is never a wire credential.
    """

    def __init__(
        self,
        authority: ProjectDispatchAuthority,
        *,
        classifier: ProjectToolClassifier | None = None,
        forwarder: AuthenticatedProjectForwarder | None = None,
        readiness: ProjectOwnerReadinessPort | None = None,
        release_manifest: ProjectOwnerReleaseManifestPort | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300:
            raise ValueError("Project dispatch timeout out of bounds")
        self.authority = authority
        self.timeout_seconds = timeout_seconds
        self._classifier = classifier
        self._forwarder = forwarder
        self._readiness = readiness
        self._release_manifest = release_manifest

    async def dispatch(
        self,
        invocation: ProjectInvocation,
        *,
        backend: str,
        tool: str,
        arguments: ProjectCommand,
        request_uuid: UUID | None = None,
    ) -> ProjectResult:
        if self._classifier is None or self._forwarder is None:
            raise ProjectGatewayDispatchUnavailable("PROJECT_DISPATCH_NOT_CONFIGURED")
        if self._readiness is None or self._release_manifest is None:
            raise ProjectGatewayDispatchUnavailable("PROJECT_OWNER_SCHEMAS_NOT_READY")
        expected_action = _PRIVATE_TOOL_ACTIONS.get((backend, tool))
        if expected_action is None:
            # Native Ghidra and arbitrary internal backends are NOT public.
            raise ProjectGatewayDispatchUnavailable("PROJECT_BACKEND_NOT_PUBLIC")
        selected_tool = _PRIVATE_TOOLS[(backend, tool)]
        if not isinstance(arguments, selected_tool.command_type):
            raise ProjectGatewayDispatchUnavailable("PROJECT_ARGUMENTS_INVALID")
        self._require_resource_provider(backend, arguments)
        forwarded_to_effect = False
        try:
            readiness = RequireOwnerReadiness(self._readiness, self._release_manifest)
            await readiness.execute(invocation, timeout_seconds=self.timeout_seconds)
            async with asyncio.timeout(self.timeout_seconds):
                request = await self._authorize_request(
                    invocation,
                    backend,
                    tool,
                    arguments,
                    request_uuid,
                    expected_action,
                )
                forwarded_to_effect = True
                return await self._forwarder.forward(request)
        except TimeoutError as exc:
            raise self._timeout_failure(backend, tool, request_uuid, forwarded_to_effect) from exc
        except ProjectGatewayDispatchUnavailable:
            raise
        except Exception as exc:
            # Internal provider/files exceptions may carry private paths,
            # HTTP headers or SDK tokens; do not echo them into MCP metadata.
            raise ProjectGatewayDispatchUnavailable("PROJECT_BACKEND_ERROR") from exc

    async def _authorize_request(
        self,
        invocation: ProjectInvocation,
        backend: str,
        tool: str,
        arguments: ProjectCommand,
        request_uuid: UUID | None,
        expected_action: ProjectAction,
    ) -> AuthorizedToolForward:
        if self._classifier is None or self._forwarder is None:
            raise ProjectGatewayDispatchUnavailable("PROJECT_DISPATCH_NOT_CONFIGURED")
        action = await self._classifier.classify(backend, tool)
        if action is None or action != expected_action:
            raise ProjectGatewayDispatchUnavailable("PROJECT_TOOL_NOT_AUTHORIZED")
        operation_uuid = self._operation_uuid(action, request_uuid)
        prepared = arguments
        if action == "files.write":
            if not isinstance(prepared, (FileUpload, FileWriteStatus)):
                raise ProjectGatewayDispatchUnavailable("PROJECT_REQUEST_UUID_MISMATCH")
            if prepared.operation_uuid != operation_uuid:
                raise ProjectGatewayDispatchUnavailable("PROJECT_REQUEST_UUID_MISMATCH")
        scope = ProjectOperationScope(
            project_id=invocation.project_id,
            agent_session_uuid=invocation.session_uuid,
            action=action,
            request_uuid=operation_uuid,
            fingerprint=self._forwarder.fingerprint(
                invocation,
                action,
                operation_uuid,
                backend,
                tool,
                prepared,
            ),
        )
        scoped = replace(invocation, operation_scope=scope)
        permit = await self.authority.require(scoped, action)
        return AuthorizedToolForward(backend, tool, prepared, permit, operation_uuid, scoped)

    @staticmethod
    def _require_resource_provider(backend: str, command: ProjectCommand) -> None:
        if isinstance(command, ResourceSelection) and (
            (backend == "observability") != (command.provider is not None)
        ):
            raise ProjectGatewayDispatchUnavailable("PROJECT_ARGUMENTS_INVALID")

    @staticmethod
    def _operation_uuid(action: ProjectAction, request_uuid: UUID | None) -> UUID:
        if request_uuid is not None:
            return checked_request_uuid(request_uuid)
        if action in _MUTATING_ACTIONS:
            raise ProjectGatewayDispatchUnavailable("PROJECT_IDEMPOTENCY_KEY_REQUIRED")
        return uuid4()

    @staticmethod
    def _timeout_failure(
        backend: str,
        tool: str,
        request_uuid: UUID | None,
        forwarded: bool,
    ) -> ProjectGatewayDispatchUnavailable:
        if not forwarded:
            return ProjectGatewayDispatchUnavailable("PROJECT_AUTHORIZATION_SCHEMA_UNAVAILABLE")
        if backend == "files" and tool == "upload_base64":
            return ProjectGatewayDispatchUnavailable(
                "PROJECT_FILE_OUTCOME_UNKNOWN",
                operation_uuid=request_uuid,
            )
        if backend == "files" and tool == "write_status":
            return ProjectGatewayDispatchUnavailable(
                "PROJECT_FILE_STATUS_UNAVAILABLE",
                operation_uuid=request_uuid,
            )
        return ProjectGatewayDispatchUnavailable("PROJECT_BACKEND_TIMEOUT")
