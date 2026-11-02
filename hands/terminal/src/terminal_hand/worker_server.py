"""Project-isolated Terminal supervisor, with no Core network or credentials.

Root is retained only by the IPC supervisor with SETUID/SETGID/KILL. The tool
process and every shell run as UID 2000 with no capabilities. Provider and
Core credentials are never mounted. Commands require a fresh signed Cedar
decision and stop when independently renewed Core authority expires.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Self
from uuid import UUID

import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from modules.terminal._public_network import encode_facts
from pydantic import ConfigDict, Field, model_validator

from hand_runtime.errors import NodePreparing
from hand_runtime.private_call import PrivateToolCall
from hand_runtime.process_lease import ProcessLease
from hand_runtime.process_lease_domain import LeaseIdentity
from hand_runtime.provider_ipc import PreparationReady
from hand_runtime.runtime_policy import child_policy_json, runtime_policy
from node_protocol.effect import EffectPermit
from runtime_peer import PeerIdentity, PeerVerifier, canonical_json
from runtime_peer.server import SignedOwnerApp, serve_unix
from terminal_hand.application.execute_operation import ExecuteOperation, UnknownOperationOutcome
from terminal_hand.application.verify_decision import VerifyTerminalDecision
from terminal_hand.domain.effect_decision import EffectBinding, OperationPrincipal
from terminal_hand.domain.human_principal import HumanOperationPrincipal
from terminal_hand.domain.operation import OperationIdentity
from terminal_hand.domain.public_network import PublicRouting
from terminal_hand.infrastructure.decision_verifier import JwtDecisionVerifier
from terminal_hand.infrastructure.human_job_execution import HumanJobExecution
from terminal_hand.infrastructure.human_job_owners import HumanJobOwners
from terminal_hand.infrastructure.node_identity import (
    ExecutionPrincipal,
    node_identity,
    node_principal,
)
from terminal_hand.infrastructure.operation_history import FileOperationHistory
from terminal_hand.infrastructure.operation_worker import SupervisorOperationWorker
from terminal_hand.infrastructure.process_cleanup import kill_execution_processes
from terminal_hand.infrastructure.worker_messages import TerminalReply
from terminal_hand.presentation.inspection import InspectionDenied, TerminalInspection

TOOLS = frozenset(
    {
        "terminal_status",
        "workspace_list",
        "workspace_create",
        "workspace_info",
        "workspace_delete",
        "terminal_exec",
        "job_start",
        "job_status",
        "job_list",
        "job_delete",
        "job_cleanup",
        "job_read",
        "job_write",
        "job_resize",
        "job_wait",
        "job_cancel",
    }
)
_UID = 2000
logger = logging.getLogger(__name__)


def require_supervisor_isolation(network_facts: PublicRouting | None = None) -> None:
    facts = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if (
        os.geteuid() != 0
        or facts["NoNewPrivs"].strip() != "1"
        or int(facts["CapEff"].strip(), 16) != (1 << 5 | 1 << 6 | 1 << 7)
        or not os.statvfs("/").f_flag & os.ST_RDONLY
    ):
        raise ValueError("Terminal supervisor must have the exact isolated worker placement")
    if network_facts is None:
        if {item.name for item in Path("/sys/class/net").iterdir()} != {"lo"}:
            raise ValueError("Offline Terminal supervisor requires loopback-only networking")
    else:
        from modules.terminal._public_network import require_kernel

        require_kernel(network_facts)


class WorkerCall(PrivateToolCall):
    model_config = ConfigDict(extra="forbid", frozen=True)
    permit: str = Field(min_length=80, max_length=8192)

    @model_validator(mode="after")
    def require_call_budget(self) -> Self:
        self.require_budget(16)
        return self


class TerminalSupervisor:
    def __init__(
        self,
        project: UUID,
        authority: PeerIdentity | None,
        state: Path,
        *,
        execution_uid: int = _UID,
        workspace_root: str = "/workspace",
        prewarm: bool = False,
        process_lease: ProcessLease | None = None,
        network_facts: PublicRouting | None = None,
    ) -> None:
        if execution_uid not in (1000, _UID) or workspace_root not in (
            "/workspace",
            "/project-data",
        ):
            raise ValueError("Approved isolated execution identity required")
        self.execution_uid, self.workspace_root, self.prewarm = (
            execution_uid,
            workspace_root,
            prewarm,
        )
        self.project, self.authority, self.state = project, authority, state
        self.child: asyncio.subprocess.Process | None = None
        self.child_ready = False
        self.lock = asyncio.Lock()
        self.lease: LeaseIdentity | None = None
        self.job_namespace: str | None = None
        self.lease_until = 0.0
        self.last_interaction = time.monotonic()
        self.process_lease = process_lease
        self.network_facts = network_facts
        self.warming: asyncio.Task[None] | None = None
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.state, 0o700)
        if self.state.stat().st_uid != 0:
            raise ValueError("Supervisor state must be inaccessible to the tool UID")
        self.human_jobs = HumanJobOwners(self.state)
        root = Path(workspace_root)
        if not root.is_dir() or root.is_symlink():
            raise ValueError("An independently provisioned project volume is required")
        self.revision = int(
            hashlib.sha256(
                canonical_json(
                    {
                        "project": str(project),
                        "device": root.stat().st_dev,
                        "inode": root.stat().st_ino,
                    }
                )
            ).hexdigest(),
            16,
        )
        self.resource = "project-terminal:" + str(project) + ":" + format(self.revision, "064x")

    def verify_permit(self, command: WorkerCall) -> OperationPrincipal:
        if self.authority is None:
            raise ValueError("Private Terminal authority is unavailable")
        effect = EffectBinding(
            self.project,
            self.resource,
            self.revision,
            command.call.name,
            hashlib.sha256(canonical_json(command.call.arguments or {})).hexdigest(),
            TOOLS | {"lease.renew"},
        )
        if self.lease is not None and len(self.lease) != 3:
            raise ValueError("Private agent lease cannot reuse human authority")
        decision = VerifyTerminalDecision(JwtDecisionVerifier(self.authority)).execute(
            command.permit,
            effect,
            self.lease,
        )
        self.lease = decision.lease_identity
        self.lease_until = time.monotonic() + max(0, decision.facts.expires_at - time.time())
        return decision.principal

    async def stop(self) -> None:
        self.child_ready = False
        if self.process_lease is not None:
            await self.process_lease.kill()
        # This PID namespace belongs exclusively to this one project worker.
        # Commands may fork or create process groups: stop every UID 2000
        # process, including descendants no longer attached to the manager.
        kill_execution_processes(self.execution_uid)
        if self.child is not None:
            with suppress(ProcessLookupError):
                await self.child.wait()
            self.child = None
        self.lease = None
        self.lease_until = 0

    async def watchdog(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            idle = runtime_policy().terminal_idle_seconds
            if (
                idle is not None
                and time.monotonic() - self.last_interaction >= idle
                and self.child is not None
            ):
                async with self.lock:
                    await self.stop()
                self.last_interaction = time.monotonic()
            if self.process_lease is not None:
                await self.process_lease.pause_expired()
            elif self.lease is not None and time.monotonic() >= self.lease_until:
                await self.stop()
            if self.prewarm and (self.child is None or self.child.returncode is not None):
                await self.warmup()

    async def grant_node(self, permit: EffectPermit) -> None:
        self.last_interaction = time.monotonic()
        if self.process_lease is None:
            raise ValueError("A rootless Node process lease is required")
        identity = node_identity(permit)
        principal = node_principal(permit)
        namespace = principal.namespace if isinstance(principal, HumanOperationPrincipal) else None
        async with self.lock:
            previous = self.process_lease.identity
            preserved = await self.process_lease.grant(identity, permit.expires_at)
            if (previous is not None and not preserved) or self.job_namespace != namespace:
                await self.stop()
                self.job_namespace = namespace
                self.warming = asyncio.create_task(self.warmup())
                self.warming.add_done_callback(
                    lambda task: None if task.cancelled() else task.exception()
                )
                raise NodePreparing("Clean Terminal preparation required for changed identity")
            self.lease = identity
            self.lease_until = time.monotonic() + max(0, permit.expires_at - time.time())

    async def close(self) -> None:
        if self.warming is not None:
            self.warming.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.warming
        await self.stop()

    async def interrupt_node(self, permit: EffectPermit) -> None:
        identity = node_identity(permit)
        async with self.lock:
            if self.process_lease is not None and self.process_lease.identity == identity:
                # A cancelled/unknown foreground effect cannot be resumed by a
                # subsequent grant. Its durable operation receipt stays unknown.
                await self.stop()
                self.warming = asyncio.create_task(self.warmup())
                self.warming.add_done_callback(
                    lambda task: None if task.cancelled() else task.exception()
                )

    async def warmup(self) -> None:
        async with self.lock:
            if self.child is None or self.child.returncode is not None:
                await self._start_child()

    async def _start_child(self) -> None:
        self.child_ready = False
        child_environment: dict[str, str] = {
            "BRIAREUS_RUNTIME_POLICY": child_policy_json(),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "PYTHONPATH": "/app/src",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "HOME": "/home/agent",
            "TERMINAL_HOME": "/home/agent",
            "TERMINAL_WORKSPACE_ROOT": self.workspace_root,
            **(
                {"TERMINAL_NETWORK_FACTS": encode_facts(self.network_facts)}
                if self.network_facts is not None
                else {}
            ),
            "TERMINAL_CHILD_READY": "1" if self.prewarm else "0",
            "TERMINAL_MAX_EXEC_OUTPUT_BYTES": "262144",
            "TERMINAL_MAX_JOB_READ_BYTES": "262144",
            "TERMINAL_MAX_JOB_LOG_BYTES": "16777216",
        }
        if self.job_namespace is not None:
            child_environment["TERMINAL_JOB_NAMESPACE"] = self.job_namespace
        self.child = await asyncio.create_subprocess_exec(
            "/app/.venv/bin/python",
            "-m",
            "terminal_hand.isolated_child",
            user=self.execution_uid,
            group=self.execution_uid,
            extra_groups=[],
            start_new_session=True,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            limit=1_000_001,
            env=child_environment,
        )
        if self.prewarm:
            try:
                async with asyncio.timeout(120):
                    if self.child.stdout is None:
                        raise ValueError("Terminal metadata startup failed")
                    ready = await self.child.stdout.readline()
                PreparationReady.decode(ready, failure="Terminal metadata startup failed")
            except BaseException:
                await self.stop()
                raise
        self.child_ready = True

    async def execute(
        self,
        command: WorkerCall,
        principal: ExecutionPrincipal,
        *,
        node_permit: EffectPermit | None = None,
    ) -> TerminalReply:
        async with self.lock:
            self._require_execution_authority(principal, node_permit)
            fingerprint = self._operation_fingerprint(command, principal)
            operation = principal.operation_uuid
            identity = OperationIdentity(operation, fingerprint)
            human = (
                HumanJobExecution(self.human_jobs, principal, command.call, fingerprint)
                if isinstance(principal, HumanOperationPrincipal)
                else None
            )
            request = (
                human.request()
                if human is not None
                else canonical_json(
                    {
                        "id": str(operation),
                        "tool": command.call.name,
                        "arguments": command.call.arguments or {},
                    }
                )
            )
            worker = SupervisorOperationWorker(
                self,
                self._start_child,
                self.stop,
                operation,
                request,
                human.validate if human is not None else None,
            )
            outcome = await ExecuteOperation(FileOperationHistory(self.state), worker).execute(
                identity
            )
            if isinstance(outcome, UnknownOperationOutcome):
                return TerminalReply(error="TERMINAL_OUTCOME_UNKNOWN")
            return outcome

    @staticmethod
    def _operation_fingerprint(command: WorkerCall, principal: ExecutionPrincipal) -> str:
        if isinstance(principal, HumanOperationPrincipal):
            payload = canonical_json(
                {
                    "human": True,
                    "actor": str(principal.actor_uuid),
                    "project": str(principal.project_uuid),
                    "tool": command.call.name,
                    "arguments": command.call.arguments or {},
                }
            )
        else:
            # Preserve existing durable agent receipt fingerprints byte-for-byte.
            payload = canonical_json(
                {
                    "actor": str(principal.actor_uuid),
                    "session": str(principal.session_uuid),
                    "tool": command.call.name,
                    "arguments": command.call.arguments or {},
                }
            )
        return hashlib.sha256(payload).hexdigest()

    def _require_execution_authority(
        self,
        principal: ExecutionPrincipal,
        permit: EffectPermit | None,
    ) -> None:
        if time.monotonic() >= self.lease_until:
            raise ValueError("Current Terminal authority expired")
        if permit is not None:
            identity = node_identity(permit)
            if (
                self.process_lease is None
                or self.process_lease.identity != identity
                or self.lease != identity
                or permit.expires_at <= time.time()
                or permit.project_uuid != self.project
                or node_principal(permit) != principal
            ):
                raise ValueError("Terminal execution owner changed")
            return
        if (
            isinstance(principal, HumanOperationPrincipal)
            or self.lease is None
            or len(self.lease) != 3
            or self.lease[:2] != (str(principal.actor_uuid), str(principal.session_uuid))
        ):
            raise ValueError("Verified private agent authority required")


def main() -> None:
    require_supervisor_isolation()
    project = UUID(os.environ["TERMINAL_PROJECT_UUID"])
    if project.version != 4:
        raise ValueError("A real project UUID is required")
    authority = PeerIdentity.from_file(
        "briareus:authorization", 1002, os.environ["ACCESS_RUNTIME_VERIFY_KEY_FILE"]
    )
    supervisor = TerminalSupervisor(project, authority, Path("/var/lib/terminal-supervisor"))

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
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
    async def inspect_resource(request: Request) -> TerminalInspection | InspectionDenied:
        if request.scope.get("briareus.service_peer") != "briareus:authorization":
            return InspectionDenied()
        return TerminalInspection(project, supervisor.resource, supervisor.revision, sorted(TOOLS))

    @app.post("/internal/v1/terminal/call")
    async def call(command: WorkerCall) -> JSONResponse:
        phase = "permit"
        try:
            claims = supervisor.verify_permit(command)
            if command.call.name == "lease.renew":
                return JSONResponse({"state": "renewed"})
            phase = "execution"
            outcome = await supervisor.execute(command, claims)
            return JSONResponse(outcome.model_dump(mode="json", by_alias=True, exclude_none=True))
        except (jwt.PyJWTError, ValueError, KeyError, TypeError) as error:
            logger.warning(
                "terminal worker rejected phase=%s category=%s", phase, type(error).__name__
            )
            return JSONResponse(
                {"error": "TERMINAL_AUTHORITY_OR_OUTCOME_UNAVAILABLE"}, status_code=503
            )

    verifier = PeerVerifier(
        "briareus:terminal-worker",
        (
            authority,
            PeerIdentity.from_file(
                "briareus:terminal", 1003, os.environ["TERMINAL_CONTROLLER_VERIFY_KEY_FILE"]
            ),
        ),
    )
    serve_unix(
        SignedOwnerApp(
            app, verifier=verifier, signing_key_file=os.environ["TERMINAL_WORKER_SIGNING_KEY_FILE"]
        ),
        os.environ["TERMINAL_WORKER_SOCKET"],
    )


if __name__ == "__main__":
    main()
