"""Signed Authorization peer adaptation for the existing private invocation route."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import (
    UUID4,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    TypeAdapter,
    ValidationInfo,
    field_validator,
)

from node_protocol.control import canonical
from node_protocol.effect import NodeWorkspaceBinding
from node_protocol.module_effects import TOOL_NAME
from projects.application.node_invocation import NodeInvocation, PrepareNodeInvocation
from projects.domain.node_administration import OperatorSelector
from projects.domain.node_invocation import (
    InfrastructureProvider,
    ProviderCall,
    ProviderModule,
    SourceCustody,
    SourceProvider,
    original_tool,
    provider_requirement,
)
from projects.domain.provider_connections import ConnectionFailure
from source_control.operations import SourceOperation

type InvocationBindingLookup = Callable[[UUID, str, Request], Awaitable[NodeWorkspaceBinding]]
_MODULE: TypeAdapter[ProviderModule] = TypeAdapter(ProviderModule)


class _AccountArgument(BaseModel):
    # The Hand owns every other argument. Retain only the custody selector.
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    account_id: StrictStr | None = None


class _OriginalToolArgument(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    tool: StrictStr


class _ProviderArgument(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    provider: InfrastructureProvider | None = None


class _SourceCommandSelector(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    # Operation existence and all non-custody parameters remain Hand authority.
    operation: SourceOperation


class _SourceRequestSelector(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    target: SourceProvider
    command: _SourceCommandSelector


class _SourceCustodyArgument(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    account_id: StrictStr | None = None
    request: _SourceRequestSelector | None = None
    target: SourceProvider | None = None
    provider: SourceProvider | None = None

    def call(self, tool: str, *, continuation: bool) -> ProviderCall:
        if tool == "source_control_capabilities" and self.account_id is not None:
            raise ValueError("Capabilities do not select an account")
        custody = self._continued_custody() if continuation else self._direct_custody(tool)
        if not custody.account_required and self.account_id is not None:
            raise ValueError("Source account catalogue does not select an account")
        return ProviderCall(tool, self.account_id, source=custody)

    def _continued_custody(self) -> SourceCustody:
        if self.provider is None or self.request is not None or self.target is not None:
            raise ValueError("Exact continued Source Control target required")
        return SourceCustody(self.provider, self.account_id is not None)

    def _direct_custody(self, tool: str) -> SourceCustody:
        if tool == "source_control_capabilities":
            if self.target is None or self.request is not None or self.provider is not None:
                raise ValueError("Explicit Source Control capability target required")
            return SourceCustody(self.target, False)
        if self.request is None or self.target is not None or self.provider is not None:
            raise ValueError("Explicit Source Control request target required")
        return SourceCustody(self.request.target, self.request.command.operation != "list_accounts")


def _continued_tool(
    module: ProviderModule, original: _OriginalToolArgument, keys: frozenset[str]
) -> str:
    allowed = {"operation_id", "tool", "account_id"}
    if module == "infrastructure" or original.tool in {
        "source_control",
        "source_control_capabilities",
    }:
        allowed.add("provider")
    if keys - allowed:
        raise ValueError("Exact bound provider continuation required")
    return original_tool(module, original.tool)


class InvocationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=12, max_length=512)
    subject: str = Field(min_length=1, max_length=256)
    project_uuid: UUID4
    actor_uuid: UUID4
    agent_session_uuid: UUID4
    grant_revision: int = Field(strict=True, ge=1)
    identity_expires_at: datetime
    module: ProviderModule
    tool: str = Field(min_length=1, max_length=128)
    arguments: ProviderCall
    binding: NodeWorkspaceBinding

    @field_validator("tool")
    @classmethod
    def exact_tool(cls, value: str) -> str:
        if TOOL_NAME.fullmatch(value) is None:
            raise ValueError("Exact bounded tool selector required")
        return value

    @field_validator("arguments", mode="before")
    @classmethod
    def custody_selectors(cls, value: object, info: ValidationInfo[None]) -> ProviderCall:
        """Project untrusted SDK input; no raw document leaves this validator."""
        module = _MODULE.validate_python(info.data.get("module"), strict=True)
        tool = info.data.get("tool")
        if not isinstance(tool, str):
            raise ValueError("Private provider module and tool required")
        if not isinstance(value, dict) or len(value) > 64:
            raise ValueError("Bounded provider arguments required")
        continuation = tool in {module + "_operation_poll", module + "_operation_cancel"}
        if tool == module + "_operation_start":
            nested = value.get("arguments")
            if set(value) != {"tool", "arguments"} or not isinstance(nested, dict):
                raise ValueError("Exact original provider invocation required")
            tool = original_tool(module, _OriginalToolArgument.model_validate(value).tool)
            value = nested
        elif continuation:
            tool = _continued_tool(
                module, _OriginalToolArgument.model_validate(value), frozenset(value)
            )
        if module == "svc" and tool in {"source_control", "source_control_capabilities"}:
            return _SourceCustodyArgument.model_validate(value).call(
                tool, continuation=continuation
            )
        required = provider_requirement(module, tool)
        account = (
            _AccountArgument.model_validate(value).account_id if required.account_required else None
        )
        provider = (
            _ProviderArgument.model_validate(value).provider
            if required.provider_argument != "unused"
            else None
        )
        return ProviderCall(tool, account, provider)

    def invocation(self) -> NodeInvocation:
        return NodeInvocation(
            OperatorSelector(
                self.issuer,
                self.subject,
                self.actor_uuid,
                self.project_uuid,
                self.identity_expires_at,
            ),
            self.module,
            self.arguments,
            self.binding,
        )


class RequestInvocationPlacement:
    def __init__(self, lookup: InvocationBindingLookup, request: Request) -> None:
        self._lookup, self._request = lookup, request

    async def current(self, project_uuid: UUID, module: ProviderModule) -> NodeWorkspaceBinding:
        return await self._lookup(project_uuid, module, self._request)


class NodeInvocationBoundary:
    def __init__(self, prepare: Callable[[Request], PrepareNodeInvocation]) -> None:
        self._prepare = prepare

    async def invoke(self, request: Request) -> JSONResponse:
        if request.scope.get("briareus.service_peer") != "briareus:authorization":
            raise HTTPException(403, "Current Authorization owner required")
        try:
            command = InvocationCommand.model_validate(await request.json())
            result = await self._prepare(request).execute(command.invocation())
            wire = result.model_dump(mode="json", exclude_unset=True)
            if len(canonical(wire["context"])) > 8192:
                raise ValueError("Bounded private invocation context required")
            return JSONResponse(wire, headers={"Cache-Control": "no-store"})
        except HTTPException:
            raise
        except ConnectionFailure as exc:
            raise HTTPException(exc.status, exc.detail) from None
        except Exception:
            raise HTTPException(503, "Private current invocation unavailable") from None
