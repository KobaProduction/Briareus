"""Typed envelopes of the existing private browser protocol."""

from uuid import UUID

from mcp.types import CallToolResult, Tool
from pydantic import BaseModel, ConfigDict, StrictBool

from hand_runtime.domain.deferred_operations import OperationState
from hand_runtime.private_call import PrivateToolCall
from runtime_peer.browser_receipts import BrowserOperationReceipt


class BrowserReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID | None = None
    result: CallToolResult | None = None
    error: str | None = None


class BrowserCatalogue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ready: StrictBool
    tools: list[Tool]

    def require_tools(self, required: frozenset[str]) -> None:
        if (
            not self.ready
            or len(self.tools) > 256
            or not required <= {tool.name for tool in self.tools}
        ):
            raise ValueError("Existing browser catalogue failed private readiness")


class BrowserCommand(PrivateToolCall):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    profile: str


class WebOperationView(BrowserOperationReceipt[OperationState, CallToolResult]):
    """The owned operation state and its original SDK reply."""
