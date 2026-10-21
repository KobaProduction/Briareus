"""Human Terminal facade shares the real Rauthy/Gateway admission adapter."""
from ._node_browser import human_module_call
TOOLS = frozenset({"terminal_status", "workspace_create", "job_start", "job_read", "job_cancel"})

async def terminal_call(*, socket, method, params, current_context, resources):
    return await human_module_call(socket=socket, method=method, params=params, current_context=current_context,
        resources=resources, module="terminal", prefix="terminal", tools=TOOLS)
