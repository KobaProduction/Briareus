"""Concrete private Terminal headers and SDK result envelopes."""

from typing import Self
from uuid import UUID

from mcp.types import CallToolResult
from pydantic import UUID4, BaseModel, ConfigDict, Field, StrictStr, model_validator
from pydantic_core import MISSING

from hand_runtime.private_call import PrivateToolCall

MAX_PRIVATE_WORKER_BYTES = 524288


class HumanJobScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    namespace: str = Field(pattern=r"^human-[a-f0-9]{64}$")
    creation_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    allowed_jobs: tuple[str, ...] | None = Field(default=None, max_length=10000)


class PrivateWorkerCommand(PrivateToolCall):
    id: UUID4
    human: HumanJobScope | None = None


class TerminalReply(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID | MISSING = MISSING
    result: CallToolResult | MISSING = MISSING
    error: str | MISSING = MISSING

    @model_validator(mode="after")
    def require_outcome(self) -> Self:
        if (self.result is MISSING) == (self.error is MISSING):
            raise ValueError("Exactly one Terminal outcome required")
        return self


class SavedOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fingerprint: StrictStr
    result: TerminalReply | MISSING = MISSING
