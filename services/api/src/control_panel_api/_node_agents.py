"""Read-only human AgentIdentity views; no synthetic agents or session grants."""
from datetime import UTC, datetime
from uuid import UUID, uuid4
from fastapi.responses import JSONResponse
from ._panel_rpc import RpcFailure

async def agents_call(*, socket, method, params, current_context, platform):
    try:
        project=UUID(params["project_uuid"])
        if project.version!=4 or str(project)!=params["project_uuid"]:raise ValueError
    except (ValueError,TypeError,AttributeError,KeyError):raise RpcFailure("AGENT_QUERY_INVALID") from None
    current=await current_context(socket,project)
    if isinstance(current,JSONResponse):raise RpcFailure("AGENT_PROJECT_ACCESS_REQUIRED")
    session,proof=current
    if platform is None:raise RpcFailure("AGENT_OWNER_UNAVAILABLE")
    deadline=min(session.expires_at,proof.expires_at)
    try:
        status,result=await platform.management({"issuer":session.issuer,"subject":session.subject,
            "operation_uuid":str(uuid4()),"action":method,"data":params},expires_at=deadline)
    except Exception:raise RpcFailure("AGENT_OWNER_UNAVAILABLE") from None
    if status!=200:raise RpcFailure("AGENT_PROJECT_ACCESS_REQUIRED" if status==403 else "AGENT_NOT_FOUND" if status==404 else "AGENT_OWNER_UNAVAILABLE")
    fresh=await current_context(socket,project)
    if (isinstance(fresh,JSONResponse) or fresh[1].user_uuid!=proof.user_uuid or fresh[0].subject!=session.subject
        or min(fresh[0].expires_at,fresh[1].expires_at)<=datetime.now(UTC)):
        raise RpcFailure("AGENT_PROJECT_ACCESS_REQUIRED")
    return result
