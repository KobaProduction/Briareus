"""Human browser controls use real provider credentials and the public MCP admission path."""
import asyncio
import json
import httpx
import logging
import re
from datetime import UTC, datetime
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, UUID4
from fastapi.responses import JSONResponse
from ._oidc_browser import _strict_browser_cookies, _SID_COOKIE
from ._oidc_origin_policy import PUBLIC_ORIGIN
from ._panel_rpc import RpcFailure
from ._resource_broker import ResourceCredentialUnavailable
from ._oidc_browser import OidcSessionStoreUnavailable
from ._oidc_id_token import OidcIdentityRejected

TOOLS = frozenset("local_browser_" + name for name in ("status", "pages", "open", "snapshot", "back", "forward", "reload",
    "close_page", "set_viewport", "click", "fill", "press", "select_option", "preview", "reopen_closed_page", "settings"))
CONTROLS = frozenset({"web_operation_start", "web_operation_poll", "web_operation_cancel"})
LOG = logging.getLogger(__name__)

def _mcp_value(reply):
    value = reply.get("structuredContent") if isinstance(reply, dict) else None
    if value is None:
        for entry in reply.get("content", []):
            if entry.get("type") == "text":
                try:
                    value = json.loads(entry["text"])
                    break
                except (ValueError, KeyError):
                    pass
    while isinstance(value, dict) and set(value) == {"result"}:
        value = value["result"]
    return value

async def prepared_exchange(exchange, frame, *, module, prefix):
    """Only replay read-only preparation; the requested effect runs once."""
    if frame.get("method") == "initialize":
        deadline = asyncio.get_running_loop().time() + 10
        while True:
            try:
                async with asyncio.timeout(max(.01, deadline - asyncio.get_running_loop().time())):
                    return await exchange(frame)
            except RpcFailure as error:
                if "OUTCOME_UNKNOWN" not in error.code:
                    raise
            except TimeoutError:
                raise RpcFailure(prefix.upper() + "_PREPARING") from None
            if asyncio.get_running_loop().time() >= deadline:
                raise RpcFailure(prefix.upper() + "_PREPARING")
            await asyncio.sleep(.5)
    status_tool = "analysis_tools" if module == "reverse" else "terminal_status" if module == "terminal" else "local_browser_status"
    status_request = frame["params"]["name"] == status_tool
    analysis_preparation = (module == "reverse" and frame["params"]["name"] in {"analysis_tools","analysis_call","analysis_start"}
        and frame["params"].get("arguments",{}).get("engine") in {"ghidra","radare2"})
    status_arguments = {"engine":frame["params"]["arguments"]["engine"]} if analysis_preparation else {}
    needs_preparation = (status_request or module == "terminal" and frame["params"]["name"] == "workspace_create"
        or module == "web" and frame["params"]["name"] == "web_operation_start" or analysis_preparation)
    if module == "reverse" and not analysis_preparation:
        needs_preparation = False  # A poll/cancel must never reset its owned operation.
    if needs_preparation:
        deadline = asyncio.get_running_loop().time() + 10
        while True:
            try:
                reply = await exchange({"jsonrpc":"2.0", "id":str(uuid4()), "method":"tools/call",
                    "params":{"name":status_tool, "arguments":status_arguments}})
                if module == "reverse" and reply.get("isError"):
                    messages = "\n".join(entry.get("text","") for entry in reply.get("content",[]) if entry.get("type")=="text")
                    if not re.search(r"\bNODE_PREPARING\b", messages):
                        if status_request:
                            return reply
                        raise RpcFailure("ANALYSIS_PREPARATION_FAILED")
                data = _mcp_value(reply)
                if not reply.get("isError") and isinstance(data, dict):
                    if (module == "web" and data.get("running") is True
                        or module == "terminal" and isinstance(data.get("workspace_root"), str)
                        or module == "reverse" and data.get("engine")==status_arguments["engine"] and isinstance(data.get("tools"),list)):
                        if status_request:
                            return reply
                        break
            except RpcFailure as error:
                if "PERMISSION_DENIED" in error.code:
                    raise
                if "OUTCOME_UNKNOWN" not in error.code:
                    raise
            if asyncio.get_running_loop().time() >= deadline:
                raise RpcFailure(prefix.upper() + "_PREPARING")
            await asyncio.sleep(.5)
    return await exchange(frame)

class BrowserCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_uuid: UUID4
    agent_session_uuid: UUID4
    expected_grant_revision: int = Field(strict=True, ge=1)
    operation_uuid: UUID4
    tool: str
    arguments: dict = Field(default_factory=dict, max_length=16)

async def browser_call(*, socket, method, params, current_context, resources):
    return await human_module_call(socket=socket, method=method, params=params, current_context=current_context,
        resources=resources, module="web", prefix="browser", tools=TOOLS, controls=CONTROLS)

async def human_module_call(*, socket, method, params, current_context, resources, module, prefix, tools, controls=frozenset()):
    try:
        if method == prefix + ".resources":
            if set(params) != {"project_uuid"}: raise ValueError
            from uuid import UUID
            project = UUID(params["project_uuid"])
            if project.version != 4: raise ValueError
            command = None
        else:
            command = BrowserCommand.model_validate(params)
            project = command.project_uuid
            if command.tool not in tools | controls: raise ValueError
            if command.tool in {"web_operation_start", "web_operation_poll"} and command.arguments.get("tool") not in tools:
                raise ValueError
    except (ValueError, KeyError, TypeError):
        raise RpcFailure(prefix.upper() + "_COMMAND_INVALID") from None
    current = await current_context(socket, project)
    if isinstance(current, JSONResponse): raise RpcFailure("CURRENT_PLATFORM_REQUIRED")
    session, proof = current
    if method == prefix + ".resources":
        if resources is None: raise RpcFailure(prefix.upper() + "_OWNER_UNAVAILABLE")
        status, reply = await resources.call("/internal/v1/resources/" + prefix + "-scope", {
            "issuer": proof.issuer, "subject": proof.subject, "actor_uuid": str(proof.user_uuid),
            "project_uuid": str(project), "identity_expires_at": min(session.expires_at, proof.expires_at).isoformat()})
        if status != 200: raise RpcFailure(prefix.upper() + "_SCOPE_UNAVAILABLE")
    else:
        escrow = getattr(socket.app.state, "resource_credentials", None)
        cookies = _strict_browser_cookies(socket)
        ticket = cookies.get(_SID_COOKIE) if cookies else None
        if escrow is None or ticket is None: raise RpcFailure(prefix.upper() + "_CREDENTIAL_UNAVAILABLE")
        try:
            credential = await escrow.resolve(ticket, module)
        except OidcIdentityRejected:
            raise RpcFailure(prefix.upper() + "_SIGN_IN_REQUIRED") from None
        except (ResourceCredentialUnavailable, OidcSessionStoreUnavailable):
            raise RpcFailure(prefix.upper() + "_CREDENTIAL_UNAVAILABLE") from None
        if (credential is None or credential.issuer != session.issuer or credential.subject != session.subject
            or credential.expires_at <= datetime.now(UTC)):
            raise RpcFailure(prefix.upper() + "_CREDENTIAL_UNAVAILABLE")
        headers = {"Authorization": "Bearer " + credential.bearer.get_secret_value(),
            "X-Briareus-Project-UUID": str(project), "X-Briareus-Agent-Session-UUID": str(command.agent_session_uuid),
            "X-Briareus-Grant-Revision": str(command.expected_grant_revision),
            "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-03-26"}
        client = escrow.provider._client
        endpoint = PUBLIC_ORIGIN + "/hands/" + module + "/mcp"
        async def _exchange(frame):
            async with client.stream("POST", endpoint, headers=headers, json=frame,
                timeout=httpx.Timeout(15, read=None)) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 1048576: raise RpcFailure(prefix.upper() + "_REPLY_TOO_LARGE")
                if response.status_code != 200:
                    try:
                        code = json.loads(body).get("code", "")
                    except (ValueError, AttributeError):
                        code = ""
                    safe_code = code if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", code) else "UNAVAILABLE"
                    LOG.warning("Human MCP response unavailable module=%s method=%s status=%s code=%s actor=%s agent_session=%s revision=%s",
                        module, frame["method"], response.status_code, safe_code, proof.user_uuid,
                        command.agent_session_uuid, command.expected_grant_revision)
                    raise RpcFailure(prefix.upper() + "_PERMISSION_DENIED" if response.status_code in {401,403} else prefix.upper() + "_OUTCOME_UNKNOWN", uncertain=True)
                if response.headers.get("mcp-session-id"): headers["MCP-Session-Id"] = response.headers["mcp-session-id"]
                raw = bytes(body).decode()
                if "text/event-stream" in response.headers.get("content-type", ""):
                    entries = [json.loads(line[5:].strip()) for line in raw.splitlines() if line.startswith("data:")]
                    decoded = next((item for item in entries if item.get("id") == frame["id"]), None)
                else: decoded = json.loads(raw)
                if not isinstance(decoded, dict) or decoded.get("id") != frame["id"] or "error" in decoded:
                    raise RpcFailure(prefix.upper() + "_OUTCOME_UNKNOWN", uncertain=True)
                return decoded["result"]
        async def exchange(frame):
            try:
                return await _exchange(frame)
            except (httpx.HTTPError, ValueError, KeyError, UnicodeError):
                # A lost reply does not mean the effect failed. Keep the panel
                # connection alive and never replay the requested mutation.
                raise RpcFailure(prefix.upper() + "_OUTCOME_UNKNOWN", uncertain=True) from None
        await prepared_exchange(exchange, {"jsonrpc":"2.0", "id":str(uuid4()), "method":"initialize", "params":{
            "protocolVersion":"2025-03-26", "capabilities":{}, "clientInfo":{"name":"briareus-human-" + prefix, "version":"1"}}}, module=module, prefix=prefix)
        try:
            initialized = await client.post(endpoint, headers=headers,
                json={"jsonrpc":"2.0", "method":"notifications/initialized"})
        except httpx.HTTPError:
            raise RpcFailure(prefix.upper() + "_INITIALIZATION_REQUIRED") from None
        if initialized.status_code not in {200,202,204}: raise RpcFailure(prefix.upper() + "_INITIALIZATION_REQUIRED")
        reply = await prepared_exchange(exchange, {"jsonrpc":"2.0", "id":str(command.operation_uuid), "method":"tools/call",
            "params":{"name":command.tool, "arguments":command.arguments}}, module=module, prefix=prefix)
    fresh = await current_context(socket, project)
    if (isinstance(fresh, JSONResponse) or fresh[1].user_uuid != proof.user_uuid
        or fresh[0].subject != session.subject or fresh[1].issuer != proof.issuer
        or min(fresh[0].expires_at, fresh[1].expires_at) <= datetime.now(UTC)):
        raise RpcFailure(prefix.upper() + "_CURRENT_AUTHORITY_REQUIRED")
    return reply
