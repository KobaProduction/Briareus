"""Strict private command decoding and canonical signed fingerprint serialization."""

from __future__ import annotations

from collections.abc import Sized
from typing import Literal
from uuid import UUID

from mcp.types import CallToolRequestParams
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from bridge.application.project_contracts import (
    FileList,
    FilePath,
    FileRead,
    FileUpload,
    FileWriteStatus,
    ProjectCommand,
    ResourceSelection,
)
from bridge.domain.project_dispatch import ArgumentBudget, ProjectGatewayDispatchUnavailable
from modules.project_runtime import ProjectAction, ProjectInvocation, canonical_request_fingerprint
from modules.project_runtime.resource_query import ResourceFilter


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Path(_Model):
    path: str = Field(min_length=1, max_length=4096)


class _FileList(_Model):
    path: str = Field(default="", max_length=4096)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)


class _Read(_Path):
    max_bytes: int = Field(default=65536, ge=1, le=262144)


class _FileUpload(_Model):
    """Only a small private MCP payload; larger transfers need a real API."""

    destination: str = Field(min_length=1, max_length=4096)
    operation_uuid: UUID
    size_bytes: int = Field(ge=0, le=262144)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_base64: str = Field(max_length=349528)

    @field_validator("operation_uuid", mode="before")
    @classmethod
    def canonical_json_uuidv4(cls, value: UUID | str) -> UUID:
        # JSON/MCP sends UUIDs as strings, even under strict Pydantic models.
        # Accept ONLY canonical, lowercase UUIDv4; never silently coerce ints.
        if isinstance(value, UUID):
            parsed = value
        elif isinstance(value, str):
            if len(value) != 36:
                raise ValueError("operation_uuid must be canonical UUIDv4")
            try:
                parsed = UUID(value)
            except ValueError as exc:
                raise ValueError("operation_uuid must be canonical UUIDv4") from exc
            if str(parsed) != value:
                raise ValueError("operation_uuid must be canonical UUIDv4")
        else:
            raise ValueError("operation_uuid must be canonical UUIDv4")
        if parsed.version != 4:
            raise ValueError("operation_uuid must be UUIDv4")
        return parsed


class _FileWriteStatus(_Model):
    operation_uuid: UUID
    # A6 SignedFilesAuthority requires the ORIGINAL canonical destination
    # when inspecting an uncertain upload. Never allow UUID-only fallback.
    destination: str = Field(min_length=1, max_length=4096)

    @field_validator("operation_uuid", mode="before")
    @classmethod
    def canonical_uuid(cls, value: UUID | str) -> UUID:
        return _FileUpload.canonical_json_uuidv4(value)


class _ResourceList(_Model):
    scope: ResourceFilter = "all"
    owner_id: UUID | None = None

    @field_validator("owner_id", mode="before")
    @classmethod
    def canonical_owner_id(cls, value: UUID | str | None) -> UUID | None:
        if value is None:
            return None
        return _FileUpload.canonical_json_uuidv4(value)


class _InfrastructureList(_ResourceList):
    provider: Literal["coolify", "signoz"]


_FILE_MODELS: dict[str, type[_Model]] = {
    "list": _FileList,
    "info": _Path,
    "sha256": _Path,
    "read_base64": _Read,
    "upload_base64": _FileUpload,
    "write_status": _FileWriteStatus,
}


def normalize_command(backend: str, request: CallToolRequestParams) -> ProjectCommand:
    require_command_input(request)
    tool = request.name
    model: type[_Model] | None = None
    if backend == "files":
        model = _FILE_MODELS.get(tool)
    elif backend in {"github", "gitlab", "variables"} and tool in {"connections", "metadata"}:
        model = _ResourceList
    elif backend == "observability" and tool == "connections":
        model = _InfrastructureList
    if model is None:
        raise ProjectGatewayDispatchUnavailable("PROJECT_TOOL_NOT_AUTHORIZED")
    try:
        parsed = model.model_validate(request.arguments or {})
    except ValidationError as exc:
        raise ProjectGatewayDispatchUnavailable("PROJECT_ARGUMENTS_INVALID") from exc
    return _command(parsed)


def _command(model: _Model) -> ProjectCommand:
    if isinstance(model, _FileList):
        return FileList(model.path, model.offset, model.limit)
    if isinstance(model, _Read):
        return FileRead(model.path, model.max_bytes)
    if isinstance(model, _Path):
        return FilePath(model.path)
    if isinstance(model, _FileUpload):
        return FileUpload(
            model.destination,
            model.operation_uuid,
            model.size_bytes,
            model.sha256,
            model.content_base64,
        )
    if isinstance(model, _FileWriteStatus):
        return FileWriteStatus(model.operation_uuid, model.destination)
    if isinstance(model, _InfrastructureList):
        return ResourceSelection(model.scope, model.owner_id, model.provider)
    if isinstance(model, _ResourceList):
        return ResourceSelection(model.scope, model.owner_id)
    raise ProjectGatewayDispatchUnavailable("PROJECT_ARGUMENTS_INVALID")


def command_model(command: ProjectCommand) -> _Model:
    if isinstance(command, FileList):
        return _FileList(path=command.path, offset=command.offset, limit=command.limit)
    if isinstance(command, FileRead):
        return _Read(path=command.path, max_bytes=command.max_bytes)
    if isinstance(command, FilePath):
        return _Path(path=command.path)
    if isinstance(command, FileUpload):
        return _FileUpload(
            destination=command.destination,
            operation_uuid=command.operation_uuid,
            size_bytes=command.size_bytes,
            sha256=command.sha256,
            content_base64=command.content_base64,
        )
    if isinstance(command, FileWriteStatus):
        return _FileWriteStatus(
            operation_uuid=command.operation_uuid, destination=command.destination
        )
    if command.provider is not None:
        return _InfrastructureList(
            scope=command.scope, owner_id=command.owner_id, provider=command.provider
        )
    return _ResourceList(scope=command.scope, owner_id=command.owner_id)


def command_fingerprint(
    invocation: ProjectInvocation,
    action: ProjectAction,
    request_uuid: UUID,
    backend: str,
    tool: str,
    command: ProjectCommand,
) -> str:
    return canonical_request_fingerprint(
        project_id=invocation.project_id,
        session_uuid=invocation.session_uuid,
        action=action,
        request_uuid=request_uuid,
        backend=backend,
        tool=tool,
        arguments=command_model(command),
    )


_FORBIDDEN_KEYS = frozenset(
    {
        "project_key",
        "session_uuid",
        "api_key",
        "api_token",
        "password",
        "secret",
        "bearer",
        "caller_evidence",
        "service_evidence",
        "authorization",
        "access_token",
        "refresh_token",
        "private_key",
        "credential",
    }
)


def _require_argument_size(value: Sized, maximum: int) -> None:
    if len(value) > maximum:
        raise ProjectGatewayDispatchUnavailable("PROJECT_ARGUMENTS_TOO_LARGE")


def _argument_key_allowed(key: str) -> bool:
    return len(key) <= 128 and key.casefold() not in _FORBIDDEN_KEYS


def _visit_argument(value: object, depth: int, budget: ArgumentBudget) -> None:
    budget.visit(depth)
    if isinstance(value, dict):
        _require_argument_size(value, 128)
        if any(not isinstance(key, str) or not _argument_key_allowed(key) for key in value):
            raise ProjectGatewayDispatchUnavailable("PROJECT_ARGUMENTS_FORBIDDEN")
        # Snapshot all children before descending, matching the original
        # reversed push/pop traversal order even for shared input objects.
        for item in tuple(value.values()):
            _visit_argument(item, depth + 1, budget)
    elif isinstance(value, list):
        _require_argument_size(value, 2048)
        for item in tuple(value):
            _visit_argument(item, depth + 1, budget)
    elif isinstance(value, str):
        _require_argument_size(value, 350000)
    elif not isinstance(value, (type(None), bool, int, float)):
        raise ProjectGatewayDispatchUnavailable("PROJECT_ARGUMENTS_INVALID")


def require_command_input(request: CallToolRequestParams) -> None:
    """Inspect raw SDK input before it can become an application command."""
    root = request.arguments or {}
    budget = ArgumentBudget()
    _visit_argument(root, 0, budget)
