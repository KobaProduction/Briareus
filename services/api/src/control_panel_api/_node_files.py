"""Human files controls retain provider credentials and current Gateway admission."""
from ._node_browser import human_module_call
from node_protocol.files import READ_TOOLS, WRITE_TOOLS
TOOLS = READ_TOOLS | WRITE_TOOLS

async def files_call(*, socket, method, params, current_context, resources):
    return await human_module_call(socket=socket, method=method, params=params, current_context=current_context,
        resources=resources, module="files", prefix="files", tools=TOOLS)
