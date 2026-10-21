"""Explicit bounded background interface for the original Web MCP tools."""


def register_operations(mcp):
    @mcp.tool()
    async def web_operation_start(tool: str, arguments: dict[str, object]):
        """Start one long original local/external Web tool after browser preparation.

        Use local_browser_status until running=true before starting. Retain
        operation_id and tool from the response, then call web_operation_poll
        every two seconds. Each poll needs current rights for the original
        tool as well as start/poll. Without fresh authority native processes
        pause within five seconds. Only one operation runs per placement.
        Never blindly retry a start whose response was lost. A worker restart
        interrupts its operations; old IDs never replay an effect.
        """
        raise RuntimeError("Metadata only; trusted supervisor executes")

    @mcp.tool()
    async def web_operation_poll(operation_id: str, tool: str):
        """Continue an owned operation and return its state and original result.

        Pass the exact tool returned by start. The supervisor independently
        matches it to the stored operation before renewing execution authority.
        Lost start reply: operation_id="request:<original start request UUID>" resolves the original handle without replay.
        Another actor, AgentSession or grant revision cannot resume or read it.
        """
        raise RuntimeError("Metadata only; trusted supervisor executes")

    @mcp.tool()
    async def web_operation_cancel(operation_id: str):
        """Stop an owned native operation without resuming it or rolling back effects.

        Browser processes stop and metadata prepares again; persistent browser
        profiles and project files remain. Other MCP placements are unaffected.
        """
        raise RuntimeError("Metadata only; trusted supervisor executes")
