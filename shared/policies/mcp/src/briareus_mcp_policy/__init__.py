from __future__ import annotations

from briareus_json_values import StrictModel
from pydantic import Field


class McpRuntimePolicy(StrictModel):
    call_timeout_seconds: int = Field(5, ge=1, le=300)
