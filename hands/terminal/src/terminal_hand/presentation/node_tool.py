"""MCP tool boundary for an admitted Terminal effect."""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.tools import ToolResult
from mcp.types import CallToolRequest, CallToolResult

from hand_runtime.errors import NodePreparing
from node_protocol.effect import HumanEffectPermit, NodeEffectPermit
from terminal_hand.infrastructure.node_identity import node_principal
from terminal_hand.worker_server import TerminalSupervisor, WorkerCall


@dataclass(frozen=True, slots=True)
class NodeTerminalTool:
    name: str
    supervisor: TerminalSupervisor
    network_check: Callable[[], None] | None = None

    async def run(self) -> ToolResult:
        call = get_http_request().scope.get("briareus.node_call")
        permit = get_http_request().scope.get("briareus.node_effect")
        if (
            not isinstance(permit, (NodeEffectPermit, HumanEffectPermit))
            or not isinstance(call, CallToolRequest)
            or call.params.name != self.name
            or permit.module != "terminal"
            or permit.tool != self.name
            or permit.method != "tools/call"
            or permit.expires_at <= time.time()
        ):
            raise ToolError("TERMINAL_CURRENT_AUTHORITY_REQUIRED")
        supervisor = self.supervisor
        principal = node_principal(permit)
        try:
            if self.network_check is not None:
                self.network_check()
            await supervisor.grant_node(permit)
            from hand_runtime.runtime_policy import runtime_policy

            async with asyncio.timeout(runtime_policy().execution_timeout_seconds):
                outcome = await supervisor.execute(
                    WorkerCall(
                        permit=get_http_request().headers["x-briareus-node-permit"],
                        call=call.params,
                    ),
                    principal,
                    node_permit=permit,
                )
            if not isinstance(outcome.result, CallToolResult) or permit.expires_at <= time.time():
                raise ValueError("Terminal outcome unavailable")
            return ToolResult.from_mcp_result(outcome.result)
        except NodePreparing:
            raise ToolError("NODE_PREPARING") from None
        except asyncio.CancelledError:
            await supervisor.interrupt_node(permit)
            raise
        except (OSError, ValueError, KeyError, TimeoutError):
            await supervisor.interrupt_node(permit)
            raise ToolError("TERMINAL_OUTCOME_UNAVAILABLE") from None
