"""Node management listener; no public Docker proxy and no MCP effect endpoint."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import httpx

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from node_protocol import NodeRecord
from node_protocol.forward import ForwardVerifier
from node_protocol.runtime import rootless_budget, validate_node_budget
from .dataplane import McpRelay, unavailable
from .control_auth import ControlRejected, CoreVerifier
from .controller import Controller
from .docker_engine import DockerEngine, EngineFailure
from .journal import Journal, OperationConflict
from .identity import NodeIdentity


def receipt(value):
    # Journal spec/previous config are private. Never serialize full SQL rows.
    result = {"operation_uuid": value["id"], "sequence": value["sequence"],
            "phase": value["phase"], "error": value["error"]}
    if value.get("diagnostic") is not None:
        result["diagnostic"] = value["diagnostic"]
    return result


def create_app(node: NodeRecord, engine: DockerEngine, journal: Journal, verifier: CoreVerifier,
               identity: NodeIdentity | None = None, forward_verifier: ForwardVerifier | None = None,
               gateway_image: str | None = None, grpc_bind: str | None = None):
    provisioned = node
    if journal is not None:
        cached = journal.configuration()
        if cached:
            restored = NodeRecord.model_validate_json(cached["record"])
            if restored.budget != provisioned.budget:
                validate_node_budget(restored.budget, provisioned.budget)
            if (restored.id != node.id
                or restored.scope != node.scope or restored.created_at != node.created_at):
                raise ValueError("Stored enrollment conflicts with bootstrap configuration")
            node = restored
    controller = Controller(node, engine, journal)
    tasks: dict[UUID, asyncio.Task] = {}
    stopping = False
    relay = None
    if forward_verifier is not None:
        if not gateway_image:
            raise ValueError("An immutable Node Gateway image is required")
        async def admit(proof):
            if stopping or not controller.node.enabled:
                raise ValueError("Node admission disabled")
            metadata = os.lstat("/node-link/gateway.sock")
            if (not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_mode & 0o077):
                raise ValueError("Private node Gateway socket required")
            try:
                container = journal.admit_forward(proof)
                current = await engine.inspect(container)
                state = current.get("State", {}) if current else {}
                labels = current.get("Config", {}).get("Labels", {}) if current else {}
                if (not state.get("Running") or state.get("Health", {}).get("Status") != "healthy"
                    or labels.get("io.briareus.node") != str(proof.node_uuid)
                    or labels.get("io.briareus.deployment") != str(proof.placement_uuid)
                    or labels.get("io.briareus.spec") != proof.fingerprint
                    or journal.forward_target(proof) != container or not controller.node.enabled):
                    raise ValueError("Current healthy placement required")
            except OperationConflict:
                raise ValueError("Current placement admission required") from None
            except EngineFailure:
                raise ValueError("Placement runtime unavailable") from None
            return "http://node-gateway/internal/v1/node/mcp"
        relay = McpRelay(verifier=forward_verifier, admit=admit, upstream_socket=True,
            client=httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds="/node-link/gateway.sock"),
                trust_env=False, follow_redirects=False, timeout=httpx.Timeout(60, connect=3)))

    @asynccontextmanager
    async def lifespan(app):
        nonlocal stopping
        grpc_server = None
        try:
            if relay is not None:
                from .gateway_runtime import ensure_gateway
                await ensure_gateway(engine, node_uuid=node.id, image=gateway_image,
                                     verify_key=os.environ["BRIAREUS_GATEWAY_VERIFY_KEY"])
                from .workspace_runtime import recover_workspace_helpers
                await recover_workspace_helpers(engine, node.id)
                from .network_policy_runtime import recover_network_policy_helpers
                await recover_network_policy_helpers(engine,node.id)
                async with asyncio.timeout(30):
                    while True:
                        try:
                            info = os.lstat("/node-link/gateway.sock")
                            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                                raise ValueError("Private Gateway socket ownership required")
                            response = await relay.client.get("http://node-gateway/health/live")
                            if response.status_code == 200 and response.json() == {"status": "live"}:
                                break
                        except (FileNotFoundError, httpx.HTTPError):
                            pass
                        await asyncio.sleep(0.5)
            if grpc_bind:
                from .grpc_server import start_server
                grpc_server = await start_server(grpc_bind, verifier=verifier, identity=identity,
                    handler=control, journal=journal, node_uuid=node.id)
            yield
        finally:
            stopping = True
            if grpc_server is not None:
                await grpc_server.stop(3)
            # Persisted phases survive cancellation. Never stop workers on exit.
            for task in list(tasks.values()):
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            if relay is not None:
                await relay.close()
            await engine.close()
            journal.close()

    async def live(request):
        return JSONResponse({"status": "live"}, headers={"Cache-Control": "no-store"})

    async def mcp(request):
        return await relay.forward(request) if relay is not None else unavailable()

    async def execute(command):
        try:
            await controller.apply(command.operation_uuid, command.sequence, command.deployment)
        except Exception as error:
            # Keep unexpected failures diagnosable without logging exception
            # text, local variables, request contents or credentials.
            import traceback
            frames = traceback.extract_tb(error.__traceback__)
            logging.getLogger(__name__).error("Node operation failed: %s at %s",
                type(error).__name__, [(Path(frame.filename).name, frame.name, frame.lineno) for frame in frames])
            current = journal.get(command.operation_uuid)
            if current and current["phase"] not in {"succeeded", "failed"}:
                journal.phase(command.operation_uuid, "failed", error="UPDATE_FAILED", diagnostic={
                    "stage":current["phase"],"component":"controller","reason":"unknown"})
        finally:
            tasks.pop(command.operation_uuid, None)

    async def control(command):
        def reply(payload, status=200):
            return status, identity.reply(command, status, payload)

        def reject(status, code):
            return reply({"error": {"code": code}}, status)

        if stopping:
            return reject(503, "NODE_DRAINING")

        if command.action == "configure":
            record = command.node_record
            if (record.scope != provisioned.scope
                or record.created_at != node.created_at):
                return reject(409, "NODE_BOOTSTRAP_CONFIGURATION_MISMATCH")
            async with controller.lock:
                try:
                    if record.budget != controller.node.budget:
                        validate_node_budget(record.budget, provisioned.budget)
                        await engine.verify_rootless()
                        allocations = [item.limits for item in await controller.observed()]
                        if not record.budget.fits(allocations):
                            return reject(409, "NODE_BUDGET_BELOW_ALLOCATIONS")
                    journal.configure(command.sequence, record)
                except OperationConflict:
                    return reject(409, "NODE_CONFIGURATION_CONFLICT")
                except ValueError:
                    return reject(409, "NODE_PROVISIONED_CAPACITY_EXCEEDED")
                except EngineFailure:
                    return reject(503, "NODE_RUNTIME_UNAVAILABLE")
                controller.node = record
            return reply({"node_uuid": str(node.id), "sequence": command.sequence,
                          "enabled": record.enabled})
        if command.action == "inventory":
            try:
                await engine.verify_rootless()
                items = await controller.observed()
            except (EngineFailure, OSError) as error:
                logging.getLogger(__name__).warning("Node inventory unavailable: %s",
                    str(error) if isinstance(error,EngineFailure) else type(error).__name__)
                return reject(503, "NODE_RUNTIME_UNAVAILABLE")
            configuration = journal.configuration()
            return reply({"node_uuid": str(node.id), "enabled": controller.node.enabled,
                "event_cursor": journal.event_cursor(),
                "sequence": configuration["sequence"] if configuration else 0, "items": [
                {"placement_uuid": str(item.deployment_uuid), "fingerprint": item.fingerprint,
                 "running": item.running, "ready": item.ready,
                 "limits": item.limits.model_dump()} for item in items]})
        if command.action == "status":
            current = journal.get(command.operation_uuid)
            if current is None:
                return reject(404, "NODE_OPERATION_NOT_FOUND")
            if current["sequence"] != command.sequence:
                return reject(409, "NODE_OPERATION_CONFLICT")
            if current["phase"]=="checking" and command.operation_uuid not in tasks:
                try:
                    current=await controller.observe_completion(command.operation_uuid,command.sequence)
                except (EngineFailure,ValueError):
                    return reject(503,"NODE_RUNTIME_UNAVAILABLE")
            return reply(receipt(current))
        if not controller.node.enabled or not command.deployment.enabled:
            return reject(403, "NODE_ADMISSION_DISABLED")
        try:
            current = journal.reserve(command.operation_uuid, command.sequence, command.deployment)
        except OperationConflict:
            return reject(409, "NODE_OPERATION_CONFLICT")
        if current["phase"] not in {"succeeded", "failed"} and command.operation_uuid not in tasks:
            if len(tasks) >= 16:
                return reject(429, "NODE_OPERATION_QUEUE_FULL")
            tasks[command.operation_uuid] = asyncio.create_task(execute(command))
        return reply(receipt(current), 202)

    app = Starlette(routes=[Route("/health/live", live),
        Route("/internal/v1/node/mcp", mcp, methods=["POST"])], lifespan=lifespan)
    app.state.node_control = control
    return app


def main():
    import uvicorn
    node = NodeRecord.model_validate_json(os.environ["BRIAREUS_NODE_RECORD"])
    rootless_budget(node.budget)
    if node.id != UUID(os.environ["BRIAREUS_NODE_UUID"]):
        raise ValueError("Configured enrollment does not match node UUID")
    verifier = CoreVerifier(os.environ["BRIAREUS_CORE_VERIFY_KEY"].encode(), node.id)
    engine = DockerEngine(f"/run/user/{os.getuid()}/docker.sock",
                          allowed_registries=frozenset(json.loads(os.environ["BRIAREUS_IMAGE_REGISTRIES"])))
    journal = Journal(Path("/var/lib/briareus-node/journal.sqlite"))
    identity = NodeIdentity(Path("/var/lib/briareus-node/node.key"))
    forward_verifier = ForwardVerifier(os.environ["BRIAREUS_GATEWAY_VERIFY_KEY"].encode(), node.id)
    uvicorn.run(create_app(node, engine, journal, verifier, identity, forward_verifier,
                os.environ["BRIAREUS_NODE_IMAGE"], grpc_bind="0.0.0.0:8081"), host="0.0.0.0", port=8080,
                access_log=False, proxy_headers=False, timeout_graceful_shutdown=10)


if __name__ == "__main__":
    main()
