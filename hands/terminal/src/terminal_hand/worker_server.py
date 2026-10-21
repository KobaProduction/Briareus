"""Project-isolated Terminal supervisor, with no Core network or credentials.

Root is retained only by the IPC supervisor with SETUID/SETGID/KILL. The tool
process and every shell run as UID 2000 with no capabilities. Provider and
Core credentials are never mounted. Commands require a fresh signed Cedar
decision and stop when independently renewed Core authority expires.
"""

from __future__ import annotations

from hand_runtime.runtime_policy import child_policy_env, runtime_policy

import asyncio
import hashlib
import json
import logging
import os
import signal
import stat
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from uuid import UUID

import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from runtime_peer import PeerIdentity, PeerVerifier, canonical_json
from runtime_peer.server import SignedOwnerApp, serve_unix
from hand_runtime.process_lease import ProcessLease

TOOLS = frozenset({"terminal_status", "workspace_list", "workspace_create", "workspace_info",
                   "workspace_delete", "terminal_exec", "job_start", "job_status", "job_list",
                   "job_delete", "job_cleanup", "job_read", "job_write", "job_resize",
                   "job_wait", "job_cancel"})
_UID = 2000
logger = logging.getLogger(__name__)


def require_supervisor_isolation(network_facts=None) -> None:
    facts = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines()
                 if ":" in line)
    if (os.geteuid() != 0 or facts["NoNewPrivs"].strip() != "1"
        or int(facts["CapEff"].strip(), 16) != (1 << 5 | 1 << 6 | 1 << 7)
        or not os.statvfs("/").f_flag & os.ST_RDONLY):
        raise ValueError("Terminal supervisor must have the exact isolated worker placement")
    if network_facts is None:
        if {item.name for item in Path("/sys/class/net").iterdir()} != {"lo"}:
            raise ValueError("Offline Terminal supervisor requires loopback-only networking")
    else:
        from modules.terminal._public_network import require_kernel
        require_kernel(network_facts)



class WorkerCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    permit: str = Field(min_length=80, max_length=8192)
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict[str, object] = Field(max_length=16)


class TerminalSupervisor:
    def __init__(self, project: UUID, authority: PeerIdentity, state: Path, *,
                 execution_uid: int = _UID, workspace_root: str = "/workspace", prewarm: bool = False,
                 process_lease: ProcessLease | None = None, network_facts=None) -> None:
        if execution_uid not in (1000, _UID) or workspace_root not in ("/workspace", "/project-data"):
            raise ValueError("Approved isolated execution identity required")
        self.execution_uid, self.workspace_root, self.prewarm = execution_uid, workspace_root, prewarm
        self.project, self.authority, self.state = project, authority, state
        self.child = None
        self.child_ready = False
        self.lock = asyncio.Lock()
        self.lease = None
        self.lease_until = 0.0
        self.last_interaction = time.monotonic()
        self.process_lease = process_lease
        self.network_facts = network_facts
        self.warming = None
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.state, 0o700)
        if self.state.stat().st_uid != 0:
            raise ValueError("Supervisor state must be inaccessible to the tool UID")
        root = Path(workspace_root)
        if not root.is_dir() or root.is_symlink():
            raise ValueError("An independently provisioned project volume is required")
        self.revision = int(hashlib.sha256(canonical_json({
            "project": str(project), "device": root.stat().st_dev, "inode": root.stat().st_ino,
        })).hexdigest(), 16)
        self.resource = "project-terminal:" + str(project) + ":" + format(self.revision, "064x")

    def verify_permit(self, command: WorkerCall) -> dict[str, object]:
        header = jwt.get_unverified_header(command.permit)
        if header.get("typ") != "briareus-effect-permit+jwt" or header.get("crit"):
            raise ValueError("A real private effect decision is required")
        claims = jwt.decode(command.permit, self.authority.public_key, algorithms=["EdDSA"],
                            issuer="briareus:authorization", audience="briareus:terminal-worker",
                            options={"require": ["iss", "aud", "iat", "nbf", "exp", "jti",
                                                 "project_uuid", "actor_uuid", "session_uuid",
                                                 "grant_revision", "tool", "arguments_digest",
                                                 "resource_id", "resource_revision", "operation_uuid"]})
        if (type(claims["iat"]) is not int or type(claims["exp"]) is not int
            or not 0 < claims["exp"] - claims["iat"] <= 5
            or claims["nbf"] != claims["iat"] or claims["project_uuid"] != str(self.project)
            or claims["resource_id"] != self.resource or claims["resource_revision"] != self.revision
            or claims["tool"] != command.tool or command.tool not in TOOLS | {"lease.renew"}
            or type(claims["grant_revision"]) is not int or claims["grant_revision"] < 1
            or claims["arguments_digest"] != hashlib.sha256(canonical_json(command.arguments)).hexdigest()):
            raise ValueError("The private decision does not bind this terminal effect")
        for field in ("jti", "actor_uuid", "session_uuid", "operation_uuid"):
            value = UUID(claims[field])
            if value.version != 4 or str(value) != claims[field]:
                raise ValueError("Canonical signed identities required")
        lease = (claims["actor_uuid"], claims["session_uuid"], claims["grant_revision"])
        if self.lease is not None and self.lease != lease:
            raise ValueError("Worker is leased to another current session")
        self.lease = lease
        self.lease_until = time.monotonic() + max(0, claims["exp"] - time.time())
        return claims

    async def stop(self) -> None:
        self.child_ready = False
        if self.process_lease is not None:
            await self.process_lease.kill()
        # This PID namespace belongs exclusively to this one project worker.
        # Commands may fork or create process groups: stop every UID 2000
        # process, including descendants no longer attached to the manager.
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                fields = dict(line.split(":", 1) for line in (entry / "status").read_text().splitlines()
                              if ":" in line)
                if int(fields["Uid"].split()[0]) == self.execution_uid:
                    os.kill(int(entry.name), signal.SIGKILL)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                pass
        if self.child is not None:
            with suppress(ProcessLookupError):
                await self.child.wait()
            self.child = None
        self.lease = None
        self.lease_until = 0

    async def watchdog(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            from hand_runtime.runtime_policy import runtime_policy
            idle=runtime_policy().terminal_idle_seconds
            if idle is not None and time.monotonic()-self.last_interaction>=idle and self.child is not None:
                async with self.lock:
                    await self.stop()
                self.last_interaction=time.monotonic()
            if self.process_lease is not None:
                await self.process_lease.pause_expired()
            elif self.lease is not None and time.monotonic() >= self.lease_until:
                await self.stop()
            if self.prewarm and (self.child is None or self.child.returncode is not None):
                await self.warmup()

    async def grant_node(self, permit) -> None:
        self.last_interaction=time.monotonic()
        if self.process_lease is None:
            raise ValueError("A rootless Node process lease is required")
        identity = (str(permit.actor_uuid), str(permit.agent_session_uuid), permit.grant_revision)
        async with self.lock:
            previous = self.process_lease.identity
            preserved = await self.process_lease.grant(identity, permit.expires_at)
            if previous is not None and not preserved:
                # A different actor/session/revision never reuses old PTYs.
                await self.stop()
                self.warming = asyncio.create_task(self.warmup())
                self.warming.add_done_callback(lambda task: None if task.cancelled() else task.exception())
                raise ValueError("Clean Terminal preparation required for changed execution identity")
            self.lease = identity
            self.lease_until = time.monotonic() + max(0, permit.expires_at - time.time())

    async def close(self) -> None:
        if self.warming is not None:
            self.warming.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.warming
        await self.stop()

    async def interrupt_node(self, permit) -> None:
        identity = (str(permit.actor_uuid), str(permit.agent_session_uuid), permit.grant_revision)
        async with self.lock:
            if self.process_lease is not None and self.process_lease.identity == identity:
                # A cancelled/unknown foreground effect cannot be resumed by a
                # subsequent grant. Its durable operation receipt stays unknown.
                await self.stop()
                self.warming = asyncio.create_task(self.warmup())
                self.warming.add_done_callback(lambda task: None if task.cancelled() else task.exception())

    async def warmup(self) -> None:
        async with self.lock:
            if self.child is None or self.child.returncode is not None:
                await self._start_child()

    async def _start_child(self) -> None:
        self.child_ready = False
        self.child = await asyncio.create_subprocess_exec(
            "/app/.venv/bin/python", "-m", "terminal_hand.isolated_child",
            user=self.execution_uid, group=self.execution_uid, extra_groups=[], start_new_session=True,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            limit=1_000_001,
            env={**child_policy_env(), "PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": "/app/src",
                 "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                 "HOME": "/home/agent", "TERMINAL_HOME": "/home/agent",
                 "TERMINAL_WORKSPACE_ROOT": self.workspace_root,
                 **({"TERMINAL_NETWORK_FACTS": json.dumps(self.network_facts, separators=(",", ":"))}
                    if self.network_facts is not None else {}),
                 "TERMINAL_CHILD_READY": "1" if self.prewarm else "0",
                 "TERMINAL_MAX_EXEC_OUTPUT_BYTES": "262144",
                 "TERMINAL_MAX_JOB_READ_BYTES": "262144",
                 "TERMINAL_MAX_JOB_LOG_BYTES": "16777216"},
        )
        if self.prewarm:
            try:
                async with asyncio.timeout(120):
                    ready = await self.child.stdout.readline()
                if json.loads(ready) != {"ready": True}:
                    raise ValueError("Terminal metadata startup failed")
            except BaseException:
                await self.stop()
                raise
        self.child_ready = True

    async def execute(self, command: WorkerCall, claims: dict[str, object]) -> dict[str, object]:
        operation = str(claims["operation_uuid"])
        target = self.state / (operation + ".json")
        fingerprint = hashlib.sha256(canonical_json({
            "actor": claims["actor_uuid"], "session": claims["session_uuid"],
            "tool": command.tool, "arguments": command.arguments,
        })).hexdigest()
        async with self.lock:
            if target.exists():
                previous = json.loads(target.read_bytes())
                if previous.get("fingerprint") != fingerprint:
                    raise ValueError("Terminal operation identity reused with changed arguments")
                return previous.get("result", {"error": "TERMINAL_OUTCOME_UNKNOWN"})
            if self.lease is None or time.monotonic() >= self.lease_until:
                raise ValueError("Current Core authority expired before dispatch")
            if len(list(self.state.glob("*.json"))) >= 10_000:
                raise ValueError("Terminal operation history capacity reached")
            with target.open("x") as pending:
                os.chmod(target, 0o600)
                json.dump({"fingerprint": fingerprint}, pending)
                pending.flush()
                os.fsync(pending.fileno())
            if self.child is None or self.child.returncode is not None:
                await self._start_child()
            child = self.child
            if self.lease is None or time.monotonic() >= self.lease_until:
                await self.stop()
                raise ValueError("Core authority expired while preparing execution")
            child.stdin.write(canonical_json({"id": operation, "tool": command.tool,
                                               "arguments": command.arguments}) + b"\n")
            await child.stdin.drain()
            raw = await child.stdout.readline()
            if not raw or len(raw) > 1_000_000:
                raise ValueError("Terminal worker did not confirm the operation")
            reply = json.loads(raw)
            if reply.get("id") != operation:
                raise ValueError("Terminal reply operation mismatch")
            result = {"fingerprint": fingerprint, "result": reply}
            temporary = target.with_suffix(".pending")
            with temporary.open("x") as completed:
                os.chmod(temporary, 0o600)
                json.dump(result, completed)
                completed.flush()
                os.fsync(completed.fileno())
            temporary.replace(target)
            return reply


def main() -> None:
    require_supervisor_isolation()
    project = UUID(os.environ["TERMINAL_PROJECT_UUID"])
    if project.version != 4:
        raise ValueError("A real project UUID is required")
    authority = PeerIdentity.from_file("briareus:authorization", 1002,
                                       os.environ["ACCESS_RUNTIME_VERIFY_KEY_FILE"])
    supervisor = TerminalSupervisor(project, authority, Path("/var/lib/terminal-supervisor"))

    @asynccontextmanager
    async def lifespan(_app):
        watchdog = asyncio.create_task(supervisor.watchdog())
        try:
            yield
        finally:
            watchdog.cancel()
            with suppress(asyncio.CancelledError):
                await watchdog
            await supervisor.stop()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/internal/v1/terminal/inspect")
    async def inspect_resource(request: Request) -> dict[str, object]:
        if request.scope.get("briareus.service_peer") != "briareus:authorization":
            return {"error": "AUTHORIZATION_OWNER_REQUIRED"}
        return {"project_uuid": str(project), "resource_id": supervisor.resource,
                "resource_revision": supervisor.revision, "tools": sorted(TOOLS),
                "isolated": True}

    @app.post("/internal/v1/terminal/call")
    async def call(command: WorkerCall) -> JSONResponse:
        phase = "permit"
        try:
            claims = supervisor.verify_permit(command)
            if command.tool == "lease.renew":
                return JSONResponse({"state": "renewed"})
            phase = "execution"
            return JSONResponse(await supervisor.execute(command, claims))
        except (jwt.PyJWTError, ValueError, KeyError, TypeError) as error:
            logger.warning("terminal worker rejected phase=%s category=%s", phase, type(error).__name__)
            return JSONResponse({"error": "TERMINAL_AUTHORITY_OR_OUTCOME_UNAVAILABLE"}, status_code=503)

    verifier = PeerVerifier("briareus:terminal-worker", (
        authority,
        PeerIdentity.from_file("briareus:terminal", 1003, os.environ["TERMINAL_CONTROLLER_VERIFY_KEY_FILE"]),
    ))
    serve_unix(SignedOwnerApp(app, verifier=verifier,
                              signing_key_file=os.environ["TERMINAL_WORKER_SIGNING_KEY_FILE"]),
                 os.environ["TERMINAL_WORKER_SOCKET"])


if __name__ == "__main__":
    main()
