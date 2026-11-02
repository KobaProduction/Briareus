"""Concrete metadata, correlated reply and operation views at the Analysis boundary."""

from fastmcp.tools import Tool
from mcp.types import CallToolResult
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr

from hand_runtime.presentation.deferred_operations import OperationStatusView
from reverse_hand.domain.dispatch import Engine


class AnalysisChildCatalogue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ready: StrictBool
    tools: tuple[Tool, ...]


class AnalysisChildReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: StrictStr
    result: CallToolResult


class AnalysisOperationView(OperationStatusView):
    engine: Engine
    result: CallToolResult | None = None
