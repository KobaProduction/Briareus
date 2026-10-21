"""Authenticated Panel event channel; never an MCP execution proxy."""
import asyncio
import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from ._oidc_origin_policy import BROWSER_ORIGIN
from ._realtime_bus import PanelEvents, REALTIME_TOPICS
from ._platform_context_dto import platform_context_payload


panel_events = PanelEvents()


def panel_events_router(*, current_context, current_user, access=None, platform=None, resources=None):
    router = APIRouter()

    @router.websocket("/api/v1/events")
    async def events(socket: WebSocket):
        if (socket.headers.getlist("origin") != [BROWSER_ORIGIN]
            or "authorization" in socket.headers or set(socket.query_params) - {"project_uuid"}):
            await socket.close(code=4403)
            return
        project = None
        if socket.query_params:
            try:
                values = socket.query_params.getlist("project_uuid")
                project = UUID(values[0])
                if len(values) != 1 or project.version != 4 or str(project) != values[0]:
                    raise ValueError
            except (ValueError, IndexError):
                await socket.close(code=4403)
                return
        context = await current_context(socket, project)
        if isinstance(context, JSONResponse):
            await socket.close(code=4401 if context.status_code == 401 else 4403)
            return
        await socket.accept()
        stream_id, sequence = str(uuid4()), 0
        send_lock = asyncio.Lock()
        module_tasks = set()
        def module_finished(task):
            module_tasks.discard(task)
            if not task.cancelled():
                task.exception()  # Disconnect can race a final response send.
        async def send(message):
            nonlocal sequence
            async with send_lock:
                if "jsonrpc" not in message:
                    sequence += 1
                    message = {**message, "stream_id": stream_id, "sequence": sequence}
                await socket.send_json(message if "jsonrpc" in message else
                    {"jsonrpc": "2.0", "method": "events.deliver", "params": message})
        async def module_reply(identifier, kind, params):
            try:
                if kind.startswith("browser."):
                    from ._node_browser import browser_call as module_call
                elif kind.startswith("terminal."):
                    from ._node_terminal import terminal_call as module_call
                elif kind.startswith("files."):
                    from ._node_files import files_call as module_call
                else:
                    from ._node_analysis import analysis_call as module_call
                result = await module_call(socket=socket,method=kind,params=params,
                    current_context=current_context,resources=resources)
                await send({"jsonrpc":"2.0","id":identifier,"result":result})
            except RpcFailure as failure:
                await send({"jsonrpc":"2.0","id":identifier,
                    "error":{"code":-32000,"message":failure.code,"data":{"uncertain":failure.uncertain}}})
            except asyncio.CancelledError:
                raise
            except Exception:
                await send({"jsonrpc":"2.0","id":identifier,
                    "error":{"code":-32000,"message":"MODULE_OWNER_UNAVAILABLE","data":{"uncertain":True}}})

        from ._owner_events import OwnerSignals
        from ._panel_rpc import PanelRpc, RpcFailure
        signals = OwnerSignals(access, platform, resources)
        rpc = PanelRpc(current_context, platform)
        topics = set(REALTIME_TOPICS)
        async with panel_events.subscribe() as queue:
            checked_context = context
            latest_proof = None
            async def relay_owners():
                # Owner journals may be slow. They must never hold up RPC,
                # heartbeat replies or the short-lived authority snapshot.
                while True:
                    proof = latest_proof
                    if proof is not None and proof.expires_at > datetime.now(UTC):
                        try:
                            async for notice in signals.read(proof):
                                await queue.put({**notice, "scope": {"kind": "broadcast"}})
                        except Exception:
                            await queue.put(panel_events.resync("owner.read_failed"))
                    await asyncio.sleep(1)

            owner_task = asyncio.create_task(relay_owners(), name="panel-owner-signals")
            incoming = asyncio.create_task(socket.receive_text())
            outgoing = asyncio.create_task(queue.get())
            try:
                while True:
                    context = checked_context if checked_context is not None else await current_context(socket, project)
                    checked_context = None
                    if isinstance(context, JSONResponse):
                        if context.status_code == 401:
                            await send({"type": "session.refresh"})
                            await socket.close(code=4401)
                        elif context.status_code == 403:
                            await socket.close(code=4403)
                        else:
                            await send({"type": "source.unavailable"})
                            await socket.close(code=1013)
                        return
                    session, proof = context
                    proof = replace(proof, expires_at=min(proof.expires_at, session.expires_at))
                    latest_proof = proof
                    now = datetime.now(UTC)
                    await send({"topic": "platform.context", "type": "snapshot",
                        "occurredAt": now.isoformat(), "data": {
                            "context": platform_context_payload(session, proof),
                            "identity": {"authenticated": True, "authority": "rauthy",
                                "issuer": session.issuer, "subject": session.subject,
                                "client_id": session.client_id, "expires_at": session.expires_at.isoformat(),
                                "platform_membership_verified": False, "permissions": []}}})
                    if (session.expires_at - now).total_seconds() < 60:
                        await send({"type": "session.refresh"})
                    # A bounded receive/publish wait, not a browser polling loop.
                    # The private delegation currently lives for at most 15s.
                    # Renew before its deadline, accounting for owner IO time.
                    interval = min(5, max(.1, (proof.expires_at - datetime.now(UTC)).total_seconds() / 2))
                    deadline = asyncio.get_running_loop().time() + interval
                    messages = 0
                    while (remaining := deadline - asyncio.get_running_loop().time()) > 0:
                        done, _ = await asyncio.wait({incoming, outgoing}, timeout=remaining,
                                                     return_when=asyncio.FIRST_COMPLETED)
                        if not done:
                            break
                        if incoming in done:
                            raw = incoming.result()
                            if len(raw) > 32768:
                                await socket.close(code=1009)
                                return
                            try:
                                message = json.loads(raw)
                                messages += 1
                                if not isinstance(message, dict) or messages > 20:
                                    raise ValueError
                                if (set(message) != {"jsonrpc", "id", "method", "params"}
                                    or message.get("jsonrpc") != "2.0"
                                    or not isinstance(message.get("id"), str) or not 1 <= len(message["id"]) <= 64
                                    or not isinstance(message.get("method"), str)
                                    or not isinstance(message.get("params"), dict)):
                                    raise ValueError
                                identifier = message["id"]
                                kind = message["method"]
                                message = message["params"]
                                if kind in {"events.subscribe", "events.unsubscribe"}:
                                    requested = message.get("topics", [message.get("topic")])
                                    if (set(message) - {"topic", "topics", "cursor"}
                                        or not isinstance(requested, list) or len(requested) > len(REALTIME_TOPICS)
                                        or any(not isinstance(t, str) or t not in REALTIME_TOPICS for t in requested)):
                                        raise ValueError
                                    cursor = message.get("cursor")
                                    if cursor is not None and (not isinstance(cursor, str) or re.fullmatch(r"[0-9]{1,16}-[0-9]{1,16}", cursor) is None):
                                        raise ValueError
                                    if kind == "events.subscribe":
                                        topics.update(requested)
                                        for event in await panel_events.replay(proof=proof, topics=set(requested), cursor=cursor):
                                            if proof.expires_at <= datetime.now(UTC):
                                                await socket.close(code=1013)
                                                return
                                            await send(event)
                                    else:
                                        topics.difference_update(requested)
                                    await send({"jsonrpc": "2.0", "id": identifier,
                                        "result": {"topics": sorted(topics)}})
                                elif kind == "events.history":
                                    requested = message.get("topics", ["mcp.calls"])
                                    before = message.get("before")
                                    limit = message.get("limit", 100)
                                    selected_project = message.get("project_uuid")
                                    if (set(message)-{"topics","before","limit","project_uuid"}
                                        or not isinstance(requested,list) or not requested or len(requested)>len(REALTIME_TOPICS)
                                        or any(not isinstance(t,str) or t not in REALTIME_TOPICS for t in requested)
                                        or type(limit) is not int or not 1 <= limit <= 100
                                        or before is not None and (not isinstance(before,str) or re.fullmatch(r"[0-9]{1,16}-[0-9]{1,16}",before) is None)
                                        or selected_project is not None and not isinstance(selected_project,str)):
                                        raise ValueError
                                    try:
                                        result = await panel_events.history(proof=proof,topics=set(requested),
                                            before=before,project=selected_project,limit=limit)
                                        fresh = await current_context(socket)
                                        if (isinstance(fresh,JSONResponse) or proof.expires_at <= datetime.now(UTC)
                                            or fresh[1].user_uuid != proof.user_uuid
                                            or fresh[1].role != proof.role
                                            or {str(p.project_uuid) for p in fresh[1].projects} != {str(p.project_uuid) for p in proof.projects}):
                                            raise ValueError("JOURNAL_CONTEXT_CHANGED")
                                        await send({"jsonrpc":"2.0","id":identifier,"result":result})
                                    except Exception:
                                        await send({"jsonrpc":"2.0","id":identifier,
                                            "error":{"code":-32000,"message":"JOURNAL_UNAVAILABLE"}})
                                elif kind == "system.ping" and not message:
                                    await send({"jsonrpc": "2.0", "id": identifier,
                                        "result": {"occurredAt": datetime.now(UTC).isoformat()}})
                                elif kind == "platform.current" and not message:
                                    reply = await current_user(socket, project)
                                    await send({"jsonrpc": "2.0", "id": identifier,
                                        **({"result": json.loads(reply.body)} if reply.status_code == 200 else
                                           {"error": {"code": -32000, "message": "Current Platform context unavailable"}})})
                                elif kind in {"platform.inventory", "platform.command", "platform.team", "platform.directory"}:
                                    try:
                                        result = await rpc.platform_call(socket, kind, message)
                                        await send({"jsonrpc": "2.0", "id": identifier, "result": result})
                                    except RpcFailure as failure:
                                        await send({"jsonrpc": "2.0", "id": identifier,
                                            "error": {"code": -32000, "message": failure.code,
                                                "data": {"uncertain": failure.uncertain}}})
                                elif kind in {"browser.resources", "browser.command", "terminal.resources", "terminal.command",
                                              "files.resources", "files.command", "analysis.resources", "analysis.command"}:
                                    if len(module_tasks) >= 8:
                                        await send({"jsonrpc":"2.0","id":identifier,
                                            "error":{"code":-32000,"message":"MODULE_REQUESTS_BUSY","data":{"uncertain":False}}})
                                    else:
                                        task=asyncio.create_task(module_reply(identifier,kind,message))
                                        module_tasks.add(task)
                                        task.add_done_callback(module_finished)
                                elif kind in {"agents.list", "agents.get"}:
                                    from ._node_agents import agents_call
                                    try:
                                        result=await agents_call(socket=socket,method=kind,params=message,current_context=current_context,platform=platform)
                                        await send({"jsonrpc":"2.0","id":identifier,"result":result})
                                    except RpcFailure as failure:
                                        await send({"jsonrpc":"2.0","id":identifier,"error":{"code":-32000,"message":failure.code}})
                                elif kind in {"nodes.inventory", "nodes.command"}:
                                    from ._node_rpc import node_call
                                    try:
                                        result = await node_call(socket=socket, method=kind, params=message,
                                            current_context=current_context, resources=resources)
                                        await send({"jsonrpc": "2.0", "id": identifier, "result": result})
                                    except RpcFailure as failure:
                                        await send({"jsonrpc": "2.0", "id": identifier,
                                            "error": {"code": -32000, "message": failure.code,
                                                "data": {"uncertain": failure.uncertain}}})
                                else:
                                    await send({"jsonrpc": "2.0", "id": identifier,
                                        "error": {"code": -32601, "message": "Method unavailable"}})
                            except (ValueError, TypeError):
                                await socket.close(code=1008)
                                return
                            incoming = asyncio.create_task(socket.receive_text())
                        if outgoing in done:
                            event = outgoing.result()
                            if (event.get("topic") in topics and panel_events.visible(event, proof)
                                and min(proof.expires_at, session.expires_at) > datetime.now(UTC)):
                                await send(event)
                            if event.get("topic") == "management.events":
                                deadline = asyncio.get_running_loop().time()
                            outgoing = asyncio.create_task(queue.get())
            except (WebSocketDisconnect, RuntimeError):
                pass
            finally:
                for task in (incoming, outgoing, owner_task, *module_tasks):
                    task.cancel()
                await asyncio.gather(incoming, outgoing, owner_task, *module_tasks, return_exceptions=True)

    return router
