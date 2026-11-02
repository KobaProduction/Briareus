"""Private UID-separated Web worker with current-Core process leases."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import stat
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from mcp.types import CallToolRequestParams, CallToolResult, TextContent, Tool

from common.runtime_policy_contracts import BrowserRuntimePolicy
from hand_runtime.application.deferred_operations import DeferredOperations
from hand_runtime.domain.deferred_operations import OperationAuthority, OperationState
from hand_runtime.errors import NodePreparing
from hand_runtime.presentation.deferred_operations import operation_handle_wire
from hand_runtime.process_lease import ProcessLease
from hand_runtime.runtime_policy import child_policy_json, runtime_policy
from node_protocol.effect import EffectPermit
from runtime_peer.browser_receipts import (
    BrowserPendingOperation,
    BrowserPreparingReceipt,
    BrowserStarting,
)

from .application.dispatch_browser import DispatchBrowser
from .application.execute_browser import ExecuteBrowser
from .application.prepare_profile import PrepareProfile, ProfileReadiness
from .domain.agent_observation import AgentBrowserObservations
from .domain.dispatch import DispatchIdentity
from .domain.profile import LeaseIdentity, ProfileObservation
from .domain.runtime_flags import require_boolean
from .infrastructure.agent_observation import capture_agent_preview
from .infrastructure.bound_execution import BoundBrowserExecution, browser_intent
from .infrastructure.browser_ipc import BrowserCatalogue, BrowserCommand, BrowserReply
from .infrastructure.execution_authority import execution_identity, require_browser_input_authority
from .infrastructure.execution_authority import profile_key as authority_profile_key
from .infrastructure.isolation import read_browser_isolation
from .infrastructure.outcome_journal import FileOutcomeJournal
from .node_runtime import EGRESS, STATIC_TOOLS
from .operation_supervisor import WebOperations

LOG = logging.getLogger(__name__)


def require_supervisor_isolation() -> None:
    read_browser_isolation().require_supervisor()


class WebSupervisor(WebOperations):
    profile: Path | None
    profile_key: str | None

    def profile_observation(self) -> ProfileObservation:
        return ProfileObservation(
            self.profile_key,
            self.process_lease.identity,
            self.child_ready,
            self.child is not None and self.child.returncode is None,
        )

    def bind_warm_profile(self, profile_key: str) -> None:
        self.profile_key = profile_key
        self.profile = Path("/browser") / ("session-" + profile_key)

    def __init__(
        self,
        *,
        browser_policy: BrowserRuntimePolicy | None = None,
        developer_access_enabled: bool = False,
        project_workspace: bool = False,
        project_workspace_read_only: bool = False,
    ) -> None:
        self.browser_policy = BrowserRuntimePolicy.model_validate(browser_policy or {})
        if type(developer_access_enabled) is not bool:
            raise ValueError("Trusted browser developer policy must be boolean")
        self.developer_access_enabled = developer_access_enabled
        require_boolean(project_workspace, "Trusted browser workspace binding required")
        require_boolean(project_workspace_read_only, "Trusted browser workspace binding required")
        self.project_workspace = project_workspace
        self.project_workspace_read_only = project_workspace_read_only
        self.process_lease = ProcessLease(uid=1000)
        self.child: asyncio.subprocess.Process | None = None
        self.child_ready = False
        self.metadata: list[Tool] = []
        self.lock = asyncio.Lock()
        self.profile = None
        self.profile_key = None
        self.status_task: asyncio.Task[BrowserReply] | None = None
        self.status_warm = False
        self.warming_task: asyncio.Task[None] | None = None
        self.deferred = DeferredOperations[CallToolResult](
            boot=uuid4(),
            lock=self.lock,
            lease=self.process_lease,
            ready=lambda: self.child_ready,
            stop=self.stop,
            recover=lambda: self.prepare_profile(self.profile_key),
            clock=time.time,
            timeout=lambda: runtime_policy().execution_timeout_seconds,
        )
        self.observations = AgentBrowserObservations()
        self.last_interaction = time.monotonic()
        self.state = Path("/var/lib/web-supervisor")
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.state.is_symlink() or (
            self.state.stat().st_uid,
            stat.S_IMODE(self.state.stat().st_mode),
        ) != (0, 0o700):
            raise ValueError("Private browser supervisor operation state required")

    async def stop(self) -> None:
        self.observations.clear()
        self.child_ready = False
        await self.process_lease.kill()
        self.deferred.interrupt()
        if self.warming_task is not None and self.warming_task is not asyncio.current_task():
            self.warming_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.warming_task
            self.warming_task = None
        self.status_warm = False
        if self.status_task is not None and self.status_task is not asyncio.current_task():
            self.status_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.status_task
        self.status_task = None
        if self.child is not None:
            with suppress(ProcessLookupError):
                await self.child.wait()
        self.child = None
        # SIGKILL cannot let Xvfb unlink its display lock/socket. A later
        # session can reuse its PID, making Xvfb mistake that stale lock for
        # a live server. Clean only our fixed endpoints after all UID 1000
        # processes have been confirmed dead; retain the private profiles.
        cleanup = await asyncio.create_subprocess_exec(
            "/app/.venv/bin/python",
            "-m",
            "web_hand.display_cleanup",
            user=1000,
            group=1000,
            extra_groups=[],
            env={
                "BRIAREUS_RUNTIME_POLICY": child_policy_json(),
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "PYTHONPATH": "/app/src",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(3):
                if await cleanup.wait() != 0:
                    raise ValueError("Private browser display cleanup failed")
        finally:
            if cleanup.returncode is None:
                with suppress(ProcessLookupError):
                    cleanup.kill()
                await cleanup.wait()
        # Persisted profiles survive process lease loss and module updates.
        # A different actor/session gets a different private directory.
        self.profile = None

    @staticmethod
    def starting(permit: EffectPermit) -> BrowserReply:
        return BrowserReply(
            id=permit.request_uuid,
            result=CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text="Browser is preparing. Poll local_browser_status "
                        "to continue with current authority.",
                    )
                ],
                structured_content=BrowserPreparingReceipt(result=BrowserStarting()).model_dump(
                    mode="json"
                ),
                is_error=False,
            ),
        )

    def prepare_profile(self, profile_key: str | None) -> None:
        if self.warming_task is not None:
            return
        self.child_ready = False
        self.profile_key = profile_key
        self.warming_task = asyncio.create_task(self.warm_profile(profile_key))

    async def warm_profile(self, profile_key: str | None) -> None:
        # Metadata imports do not launch Chrome or execute a browser tool.
        # They must not consume a short effect permit or retry native effects.
        for attempt, delay in enumerate((0, 5, 15), 1):
            await asyncio.sleep(delay)
            try:
                async with self.lock:
                    await self.stop()
                    await self.start(profile_key)
                self.warming_task = None
                return
            except Exception:
                LOG.warning("Web metadata preparation failed (attempt %d/3)", attempt)

    async def start(self, profile_key: str | None = None) -> None:
        self.observations.clear()
        self.child_ready = False
        profile = Path("/browser") / ("session-" + (profile_key or "metadata"))
        # UID 0 deliberately has no DAC_OVERRIDE; /browser is owned by UID
        # 1000:0700. Only the already-dropped child creates/reads its profile.
        self.profile = profile
        self.profile_key = profile_key
        self.child = await asyncio.create_subprocess_exec(
            "/app/.venv/bin/python",
            "-m",
            "web_hand.isolated_child",
            user=1000,
            group=1000,
            extra_groups=[],
            start_new_session=True,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            limit=1_000_001,
            env={
                "BRIAREUS_RUNTIME_POLICY": child_policy_json(),
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "PYTHONPATH": "/app/src",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
                "HOME": str(profile),
                "TMPDIR": tempfile.gettempdir(),
                "BRIAREUS_NODE_WEB_PROFILE": str(profile),
                "BRIAREUS_NODE_WEB_PROJECT_WORKSPACE": "1" if self.project_workspace else "0",
                "BRIAREUS_NODE_WEB_PROJECT_READ_ONLY": "1"
                if self.project_workspace_read_only
                else "0",
                "BRIAREUS_NODE_WEB_EGRESS": EGRESS,
                "BRIAREUS_NODE_WEB_POLICY": self.browser_policy.model_dump_json(),
                "BRIAREUS_NODE_WEB_DEVELOPER_ACCESS": "1" if self.developer_access_enabled else "0",
                "HTTP_PROXY": EGRESS,
                "HTTPS_PROXY": EGRESS,
                "NO_PROXY": "127.0.0.1,localhost,::1",
                "no_proxy": "127.0.0.1,localhost,::1",
                "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS": "1",
                "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS": "1",
                "CHROME_DEVTOOLS_MCP_NO_CONFIG_DISCOVERY": "1",
            },
        )
        try:
            async with asyncio.timeout(120):
                stdout = self.child.stdout
                if stdout is None:
                    raise ValueError("Private browser output pipe required")
                raw = await stdout.readline()
            reply = BrowserCatalogue.model_validate_json(raw)
            reply.require_tools(STATIC_TOOLS)
            self.metadata = reply.tools
            self.child_ready = True
        except BaseException:
            await self.stop()
            raise

    async def watchdog(self) -> None:
        while True:
            await asyncio.sleep(0.05)
            try:
                await self.process_lease.pause_expired()
                idle = runtime_policy().web_tab_idle_seconds
                if (
                    idle is not None
                    and self.profile_key is not None
                    and time.monotonic() - self.last_interaction >= idle
                ):
                    # Maintenance may kill expired sessions; never resume the
                    # untrusted UID merely to execute a page.close command.
                    async with self.lock:
                        await self.stop()
                        self.profile_key = None
                        self.last_interaction = time.monotonic()
                        self.prepare_profile(None)
                if (
                    self.child is None or self.child.returncode is not None
                ) and self.warming_task is None:
                    async with self.lock:
                        if (
                            self.child is None or self.child.returncode is not None
                        ) and self.warming_task is None:
                            self.prepare_profile(self.profile_key)
            except Exception:
                await self.stop()
                await asyncio.sleep(1)

    async def execute(
        self,
        call: CallToolRequestParams,
        permit: EffectPermit,
    ) -> BrowserReply:
        self.last_interaction = time.monotonic()
        if self.warming_task is not None and not self.warming_task.done():
            if call.name == "local_browser_status" and not call.arguments:
                return self.starting(permit)
            raise NodePreparing
        async with self.lock:
            identity = execution_identity(permit)
            profile_key = authority_profile_key(permit)
            return await ExecuteBrowser(BoundBrowserExecution(self, call, permit)).execute(
                browser_intent(call),
                OperationAuthority(identity, permit.expires_at, permit.request_uuid),
                profile_key,
            )

    def operation_running(self) -> bool:
        return self.deferred.book.running()

    def pending_status(self, identity: LeaseIdentity, permit: EffectPermit) -> BrowserReply:
        record = next(
            (
                item
                for item in self.deferred.book.values()
                if item.state == OperationState.RUNNING and item.identity == identity
            ),
            None,
        )
        if record is None:
            raise ValueError("Browser operation unavailable for this execution identity")
        return BrowserReply(
            id=permit.request_uuid,
            result=CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text="Continue the existing browser operation with current authority.",
                    )
                ],
                structured_content=BrowserPreparingReceipt(
                    result=BrowserStarting(
                        pending=BrowserPendingOperation(
                            operation_id=operation_handle_wire(record.operation_id),
                            tool=record.tool,
                        ),
                    )
                ).model_dump(mode="json"),
                is_error=False,
            ),
        )

    async def prepare_execution(
        self, profile_key: str, identity: LeaseIdentity
    ) -> ProfileReadiness:
        return await PrepareProfile(self).execute(profile_key, identity)

    def startup_pending(self) -> bool:
        return self.status_task is not None

    def startup_complete(self) -> bool:
        return self.status_warm

    async def grant_execution(self, identity: LeaseIdentity, expires_at: float) -> None:
        await self.process_lease.grant(identity, expires_at)

    async def authorized_status(
        self,
        call: CallToolRequestParams,
        permit: EffectPermit,
    ) -> BrowserReply:
        if call.arguments:
            raise ValueError("Exact browser status arguments required")
        if self.status_task is None:
            self.status_task = asyncio.create_task(self.exchange(call, permit, startup=True))
            self.status_task.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        if not self.status_task.done():
            return self.starting(permit)
        try:
            reply = self.status_task.result()
            self.status_warm = reply.result is not None and not reply.result.is_error
            self.status_task = None
            return reply
        except BaseException:
            await self.stop()
            raise

    async def exchange(
        self,
        call: CallToolRequestParams,
        permit: EffectPermit,
        *,
        startup: bool = False,
        background: bool = False,
    ) -> BrowserReply:
        require_browser_input_authority(permit, call.name)
        identity = execution_identity(permit)
        fingerprint = hashlib.sha256(
            json.dumps(
                {"identity": identity, "tool": call.name, "arguments": call.arguments or {}},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        dispatch = DispatchIdentity(permit.request_uuid, fingerprint)

        async def invoke() -> BrowserReply:
            generation = self.observations.generation
            child = self.child
            if child is None or child.stdin is None or child.stdout is None:
                raise ValueError("Prepared browser private pipes required")
            command = BrowserCommand(id=dispatch.operation, call=call, profile=str(self.profile))
            timeout = (
                120 if startup else None if background else max(0, permit.expires_at - time.time())
            )
            async with asyncio.timeout(timeout):
                payload = command.wire_json(sort_keys=True, compact=True).encode()
                child.stdin.write(payload + b"\n")
                await child.stdin.drain()
                raw = await child.stdout.readline()
            if len(raw) > 1000000:
                raise ValueError("Browser private response exceeded output limit")
            reply = BrowserReply.model_validate_json(raw)
            if reply.id != dispatch.operation or (
                not (startup or background) and permit.expires_at <= time.time()
            ):
                raise ValueError("Browser operation outcome unavailable")
            capture_agent_preview(self.observations, generation, permit, call.name, reply)
            return reply

        return await DispatchBrowser(FileOutcomeJournal(self.state), self.stop).execute(
            dispatch,
            invoke,
            deferred=startup or background,
        )
