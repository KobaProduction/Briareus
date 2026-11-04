from __future__ import annotations

from typing import Literal

from briareus_json_values import StrictModel
from pydantic import Field


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


class InvocationEventBatch(StrictModel):
    events: list[InvocationEvent] = Field(min_length=1, max_length=128)
