"""Gateway-owned envelopes around opaque MCP schemas and tool values."""

from typing import Literal

from briareus_json_values import JsonObject, JsonValue, StrictModel
from pydantic import Field


class BackendStatus(StrictModel):
    name: str
    public_path: str
    purpose: str
    status: Literal["available", "not_available"]
    tool_count: int
    error_type: str | None = None


class BackendInventory(StrictModel):
    status: Literal["ok"] = "ok"
    backends: list[BackendStatus]
    count: int


class RemoteToolDescription(StrictModel):
    name: str
    description: str
    title: str | None = None
    input_schema: JsonObject | None = None
    output_schema: JsonObject | None = None


class AvailableTools(StrictModel):
    backend: str
    public_path: str
    status: Literal["available"] = "available"
    tools: list[RemoteToolDescription]
    count: int


class UnavailableTools(StrictModel):
    backend: str
    public_path: str
    status: Literal["not_available"] = "not_available"
    tools: list[RemoteToolDescription] = Field(default_factory=list)
    error_type: str


class BackendCallSuccess(StrictModel):
    backend: str
    tool: str
    status: Literal["ok"] = "ok"
    result: JsonValue


class BackendCallFailure(StrictModel):
    backend: str
    tool: str
    status: Literal["error"] = "error"
    error_type: str
    message: str
    hint: str
