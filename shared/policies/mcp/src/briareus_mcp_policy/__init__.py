from __future__ import annotations

from briareus_json_values import StrictModel
from pydantic import Field


class McpRuntimePolicy(StrictModel):
    call_timeout_seconds: int = Field(0, ge=0, le=300)
