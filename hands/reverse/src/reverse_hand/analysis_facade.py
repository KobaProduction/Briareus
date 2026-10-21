"""One Analysis MCP catalogue; engine IDs select actual engine capabilities."""
from typing import Literal

Engine = Literal["ghidra", "radare2"]


def register_facade(mcp):
    @mcp.tool()
    async def analysis_tools(engine: Engine):
        """Describe the selected engine's actual tools and JSON argument schemas.

        Use these names and schemas with analysis_call. Engines share one
        project-private Analysis placement, but have distinct capabilities.
        """
        raise RuntimeError("Metadata-only facade; isolated dispatcher executes")

    @mcp.tool()
    async def analysis_call(engine: Engine, tool: str, arguments: dict[str, object]):
        """Call one actual tool from analysis_tools(engine), with its exact arguments.

        The signed effect binds engine, tool and all nested arguments. The
        current analysis.import grant is module-wide; nested per-engine tool
        grants are not implemented. Unsupported operations fail closed.
        """
        raise RuntimeError("Metadata-only facade; isolated dispatcher executes")

    @mcp.tool()
    async def analysis_start(engine: Engine, tool: str, arguments: dict[str, object]):
        """Start one long engine operation and return its server-issued operation_id.

        Use analysis_poll at least once every two seconds to maintain current
        execution authority. Without fresh authorized polls native processes
        pause within five seconds. Only one operation runs per placement.
        Never blindly repeat a start whose response was lost: it may already
        have changed the project. Operations are interrupted by worker restart;
        their IDs are not durable handles and never restart an operation.
        """
        raise RuntimeError("Metadata-only facade; isolated dispatcher executes")

    @mcp.tool()
    async def analysis_poll(operation_id: str):
        """Resume an owned operation with current rights and return state/result.

        Requires both analysis_poll and analysis_start grants on this Analysis
        resource. Only the original actor, AgentSession and grant revision may
        resume or retrieve it. Lost start reply: operation_id="request:<original start request UUID>" resolves the handle without replay. Unknown or old worker IDs never start work.
        """
        raise RuntimeError("Metadata-only facade; trusted supervisor executes")

    @mcp.tool()
    async def analysis_cancel(operation_id: str):
        """Stop an owned operation's native processes without resuming them.

        Completed effects are not rolled back. The private engines prepare
        again after cancellation; other placements are unaffected.
        """
        raise RuntimeError("Metadata-only facade; trusted supervisor executes")
