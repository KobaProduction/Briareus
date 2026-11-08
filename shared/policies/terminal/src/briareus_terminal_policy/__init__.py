from __future__ import annotations

from briareus_json_values import StrictModel
from pydantic import Field


class TerminalRuntimePolicy(StrictModel):
    max_concurrent_processes: int = Field(16, ge=1, le=256)
    max_exec_timeout_seconds: int = Field(21_600, ge=1, le=86_400)
    max_job_runtime_seconds: int = Field(43_200, ge=1, le=604_800)
