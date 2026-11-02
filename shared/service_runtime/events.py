"""Invocation telemetry wire contract shared by producers and sinks."""

from typing import Literal

from pydantic import Field

from .models import StrictModel


class InvocationEvent(StrictModel):
    request_id: str = ""
    module: str = Field(min_length=1, max_length=64)
    tool: str = Field(min_length=1, max_length=256)
    account_id: str = ""
    provider: str = ""
    status: Literal["success", "error"]
    duration_ms: float = Field(ge=0)
    error_type: str = ""
    arguments_json: str = ""
    result_json: str = ""
    error_message: str = ""
