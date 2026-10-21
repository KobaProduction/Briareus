"""Private UID-separated Web worker with current-Core process leases."""
from __future__ import annotations

from hand_runtime.runtime_policy import child_policy_env, runtime_policy

import asyncio
import hashlib
import json
import logging
import os
import stat
import time
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from hand_runtime.process_lease import ProcessLease
from node_protocol.control import canonical
from common.runtime_policy_contracts import BrowserRuntimePolicy

from .node_runtime import EGRESS, STATIC_TOOLS
from .operation_supervisor import WebOperations

LOG = logging.getLogger(__name__)


def require_supervisor_isolation():
    facts = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    if (os.geteuid() != 0 or facts["NoNewPrivs"].strip() != "1"
        or int(facts["CapEff"].strip(), 16) != (1 << 5 | 1 << 6 | 1 << 7)
        or not os.statvfs("/").f_flag & os.ST_RDONLY
        or Path("/var/run/docker.sock").exists()
        or {item.name for item in Path("/sys/class/net").iterdir()} != {"lo", "eth0"}):
        raise ValueError("Isolated rootless browser supervisor placement required")


class WebSupervisor(WebOperations):
    def __init__(self, *, browser_policy=None, developer_access_enabled=False, project_workspace=False, project_workspace_read_only=False):
        self.browser_policy = BrowserRuntimePolicy.model_validate(browser_policy or {})
        if type(developer_access_enabled) is not bool:
            raise ValueError("Trusted browser developer policy must be boolean")
        self.developer_access_enabled = developer_access_enabled
        if type(project_workspace) is not bool or type(project_workspace_read_only) is not bool:
            raise ValueError("Trusted browser workspace binding required")
        self.project_workspace = project_workspace
        self.project_workspace_read_only = project_workspace_read_only
        self.process_lease = ProcessLease(uid=1000)
        self.child = None
        self.child_ready = False
        self.metadata = []
        self.lock = asyncio.Lock()
        self.profile = None
        self.profile_key = None
        self.status_task = None
        self.status_warm = False
        self.warming_task = None
        self.boot = str(uuid4())
        self.operations = {}
        self.last_interaction=time.monotonic()
        self.state = Path("/var/lib/web-supervisor")
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.state.is_symlink() or (self.state.stat().st_uid, stat.S_IMODE(self.state.stat().st_mode)) != (0, 0o700):
            raise ValueError("Private browser supervisor operation state required")

    async def stop(self):
        self.child_ready = False
        await self.process_lease.kill()
        for record in self.operations.values():
            if record["state"] == "running":
                record["state"] = "interrupted"
                task = record.get("task")
                if task is not None and task is not asyncio.current_task():
                    task.cancel()
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
            "/app/.venv/bin/python", "-m", "web_hand.display_cleanup",
            user=1000, group=1000, extra_groups=[],
            env={**child_policy_env(), "PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": "/app/src",
                 "PYTHONDONTWRITEBYTECODE": "1"},
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
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
    def starting(permit):
        return {"id":str(permit.request_uuid),"result":{
            "content":[{"type":"text","text":"Browser is preparing. Poll local_browser_status to continue with current authority."}],
            "structuredContent":{"result":{"running":False,"starting":True,"cdp_reachable":False}},
            "isError":False}}

    def prepare_profile(self, profile_key):
        if self.warming_task is not None:
            return
        self.profile_key = profile_key
        self.warming_task = asyncio.create_task(self.warm_profile(profile_key))

    async def warm_profile(self, profile_key):
        # Metadata imports do not launch Chrome or execute a browser tool.
        # They must not consume a short effect permit or retry native effects.
        for attempt, delay in enumerate((0,5,15),1):
            await asyncio.sleep(delay)
            try:
                async with self.lock:
                    await self.stop()
                    await self.start(profile_key)
                self.warming_task = None
                return
            except Exception:
                LOG.warning("Web metadata preparation failed (attempt %d/3)",attempt)

    async def start(self, profile_key=None):
        self.child_ready = False
        profile = Path("/browser") / ("session-" + (profile_key or "metadata"))
        # UID 0 deliberately has no DAC_OVERRIDE; /browser is owned by UID
        # 1000:0700. Only the already-dropped child creates/reads its profile.
        self.profile = profile
        self.profile_key = profile_key
        self.child = await asyncio.create_subprocess_exec(
            "/app/.venv/bin/python", "-m", "web_hand.isolated_child",
            user=1000, group=1000, extra_groups=[], start_new_session=True,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, limit=1_000_001,
            env={**child_policy_env(), "PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": "/app/src",
                 "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                 "HOME": str(profile), "TMPDIR": "/tmp",
                 "BRIAREUS_NODE_WEB_PROFILE": str(profile),
                 "BRIAREUS_NODE_WEB_PROJECT_WORKSPACE": "1" if self.project_workspace else "0",
                 "BRIAREUS_NODE_WEB_PROJECT_READ_ONLY": "1" if self.project_workspace_read_only else "0", "BRIAREUS_NODE_WEB_EGRESS": EGRESS,
                 "BRIAREUS_NODE_WEB_POLICY": self.browser_policy.model_dump_json(),
                 "BRIAREUS_NODE_WEB_DEVELOPER_ACCESS": "1" if self.developer_access_enabled else "0",
                 "HTTP_PROXY": EGRESS, "HTTPS_PROXY": EGRESS,
                 "NO_PROXY": "127.0.0.1,localhost,::1", "no_proxy": "127.0.0.1,localhost,::1",
                 "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS": "1",
                 "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS": "1",
                 "CHROME_DEVTOOLS_MCP_NO_CONFIG_DISCOVERY": "1"},
        )
        try:
            async with asyncio.timeout(120):
                raw = await self.child.stdout.readline()
            reply = json.loads(raw)
            if (not isinstance(reply, dict) or set(reply) != {"ready", "tools"}
                or reply["ready"] is not True or not isinstance(reply["tools"], list)
                or len(reply["tools"]) > 256 or not STATIC_TOOLS <= {item["name"] for item in reply["tools"]}):
                raise ValueError("Existing browser catalogue failed private readiness")
            self.metadata = reply["tools"]
            self.child_ready = True
        except BaseException:
            await self.stop()
            raise

    async def watchdog(self):
        while True:
            await asyncio.sleep(0.05)
            try:
                await self.process_lease.pause_expired()
                idle=runtime_policy().web_tab_idle_seconds
                if idle is not None and self.profile_key is not None and time.monotonic()-self.last_interaction>=idle:
                    # Maintenance may kill expired sessions; never resume the
                    # untrusted UID merely to execute a page.close command.
                    async with self.lock:
                        await self.stop()
                        self.profile_key=None
                        self.last_interaction=time.monotonic()
                        self.prepare_profile(None)
                if (self.child is None or self.child.returncode is not None) and self.warming_task is None:
                    async with self.lock:
                        if (self.child is None or self.child.returncode is not None) and self.warming_task is None:
                            self.prepare_profile(self.profile_key)
            except Exception:
                await self.stop()
                await asyncio.sleep(1)

    async def execute(self, tool, arguments, permit):
        self.last_interaction=time.monotonic()
        async with self.lock:
            identity = (str(permit.actor_uuid), str(permit.agent_session_uuid), permit.grant_revision)
            if tool in {"web_operation_poll", "web_operation_cancel"}:
                return await self.operation_control(tool, arguments, permit, identity)
            if any(item["state"] == "running" for item in self.operations.values()):
                raise ValueError("Web operation in progress; poll or cancel it first")
            profile_key = hashlib.sha256(canonical(identity[:2])).hexdigest()
            if self.profile_key is None and self.process_lease.identity is None and self.child_ready:
                # The original tools and DevTools metadata are already warm.
                # Bind the unstarted BrowserManager inside that child, without
                # spending a first effect's five-second lease on Python imports.
                self.profile_key = profile_key
                self.profile = Path("/browser") / ("session-" + profile_key)
            elif self.profile_key != profile_key or self.process_lease.identity not in {None, identity}:
                await self.stop()
                self.prepare_profile(profile_key)
                if tool == "local_browser_status" and not arguments:
                    return self.starting(permit)
                raise ValueError("Clean browser session preparing; poll local_browser_status")
            elif self.child is None or self.child.returncode is not None:
                self.prepare_profile(profile_key)
                if tool == "local_browser_status" and not arguments:
                    return self.starting(permit)
                raise ValueError("Browser metadata preparing; poll local_browser_status")
            if self.status_task is not None and tool != "local_browser_status":
                # Only another authorized status request may renew the
                # authority of a pending status/startup operation.
                raise ValueError("Browser is starting; poll local_browser_status first")
            if tool == "web_operation_start":
                return await self.operation_start(arguments, permit, identity)
            await self.process_lease.grant(identity, permit.expires_at)
            if tool == "local_browser_status" and not self.status_warm:
                if arguments:
                    raise ValueError("Exact browser status arguments required")
                if self.status_task is None:
                    self.status_task = asyncio.create_task(self.exchange(tool, arguments, permit, startup=True))
                    self.status_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
                if not self.status_task.done():
                    return self.starting(permit)
                try:
                    reply = self.status_task.result()
                    self.status_warm = "result" in reply and not reply["result"].get("isError")
                    self.status_task = None
                    return reply
                except BaseException:
                    await self.stop()
                    raise
            return await self.exchange(tool, arguments, permit)

    async def exchange(self, tool, arguments, permit, *, startup=False, background=False):
        identity = (str(permit.actor_uuid), str(permit.agent_session_uuid), permit.grant_revision)
        # Startup is the existing read-only status operation, never an
        # arbitrary deferred browser effect. Its execution UID remains
        # subject to the independent short ProcessLease watchdog.
        operation = str(permit.request_uuid)
        target = self.state / (operation + ".json")
        fingerprint = hashlib.sha256(canonical({"identity": identity, "tool": tool, "arguments": arguments})).hexdigest()
        if target.exists():
            saved = json.loads(target.read_bytes())
            if saved.get("fingerprint") != fingerprint:
                raise ValueError("Browser operation identity reused")
            return saved.get("result", {"error": "WEB_OUTCOME_UNKNOWN"})
        if len(list(self.state.glob("*.json"))) >= 10_000:
            raise ValueError("Browser operation history capacity exceeded")
        with target.open("x") as handle:
            os.chmod(target, 0o600)
            json.dump({"fingerprint": fingerprint}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            async with asyncio.timeout(120 if startup else None if background else max(0, permit.expires_at - time.time())):
                self.child.stdin.write(canonical({"id": operation, "tool": tool, "arguments": arguments,
                                                  "profile": str(self.profile)}) + b"\n")
                await self.child.stdin.drain()
                raw = await self.child.stdout.readline()
            if len(raw) > 1_000_000:
                raise ValueError("Browser private response exceeded output limit")
            reply = json.loads(raw)
            if reply.get("id") != operation or not (startup or background) and permit.expires_at <= time.time():
                raise ValueError("Browser operation outcome unavailable")
            temporary = target.with_suffix(".pending")
            with temporary.open("x") as handle:
                os.chmod(temporary, 0o600)
                json.dump({"fingerprint": fingerprint, "result": reply}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(target)
            return reply
        except BaseException:
            # A partial IPC reply may not be reused by a later operation.
            # Background startup errors are consumed under execute's lock
            # by the next status call; only its own authority may resume it.
            if not (startup or background):
                await self.stop()
            raise
