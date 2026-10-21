"""Human analysis controls retain provider credentials and current Gateway admission."""
from ._node_browser import human_module_call
TOOLS = frozenset({"analysis_tools", "analysis_call", "analysis_start", "analysis_poll", "analysis_cancel"})

async def analysis_call(*, socket, method, params, current_context, resources):
    return await human_module_call(socket=socket, method=method, params=params, current_context=current_context,
        resources=resources, module="reverse", prefix="analysis", tools=TOOLS)
