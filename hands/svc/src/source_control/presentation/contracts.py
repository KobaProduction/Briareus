"""Closed common operation names and exact provider parameter contracts."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from source_control.operations import SourceOperation as SourceOperation
from source_control.operations import SourceTarget as SourceTarget


class SourceParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    tool_name: ClassVar[str]
    operation_name: ClassVar[SourceOperation]


class SourceCapability(BaseModel):
    operation: SourceOperation
    provider_tool: str


class SourceCapabilities(BaseModel):
    target: SourceTarget
    operations: tuple[SourceCapability, ...]
