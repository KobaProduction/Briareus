"""Project a signed SC request into its existing operation permission identifier."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from source_control.operations import SourceOperation, SourceTarget, provider_tool


class _Command(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    operation: SourceOperation


class _Target(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    target: SourceTarget
    command: _Command


class _SourceArguments(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    request: _Target

    def permission(self) -> str:
        return provider_tool(self.request.target, self.request.command.operation)


class _DirectParameters(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    name: Literal["source_control"]
    arguments: _SourceArguments


class _DirectRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    params: _DirectParameters


class _StartedArguments(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    tool: Literal["source_control"]
    arguments: _SourceArguments


class _StartedParameters(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    name: Literal["svc_operation_start"]
    arguments: _StartedArguments


class _StartedRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    params: _StartedParameters


def source_delegation(tool: str | None, original: str | None, body: bytes) -> str | None:
    if tool == "source_control":
        return _DirectRequest.model_validate_json(body).params.arguments.permission()
    if tool == "svc_operation_start" and original == "source_control":
        return _StartedRequest.model_validate_json(body).params.arguments.arguments.permission()
    return None
