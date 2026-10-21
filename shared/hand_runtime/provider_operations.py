"""Provider continuations with exact original account selection on every poll."""
def register_provider_operations(mcp,module):
    @mcp.tool(name=module+"_operation_start")
    async def start(tool:str,arguments:dict[str,object]):
        """Start one long original provider tool. Poll every2seconds with handle, exact tool and original account_id. Start/poll need original-tool rights; processes pause without fresh Core authority. Never replay a start after lost reply."""
        raise RuntimeError("Metadata only")
    @mcp.tool(name=module+"_operation_poll")
    async def poll(operation_id:str,tool:str,account_id:str|None=None,provider:str|None=None):
        """Resume an owned operation using the exact original account_id (null for account-list tools). Current tool+start+poll rights required. Changed actor/session/revision/account cannot resume it. Lost start reply: operation_id="request:<original start request UUID>" resolves its handle without replay."""
        raise RuntimeError("Metadata only")
    @mcp.tool(name=module+"_operation_cancel")
    async def cancel(operation_id:str,tool:str,account_id:str|None=None,provider:str|None=None):
        """Stop an owned operation without resuming it. Pass exact original tool/account_id. Existing external effects are not rolled back."""
        raise RuntimeError("Metadata only")
