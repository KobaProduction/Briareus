"""Trusted rootless parent; native parsers never share its UID or memory."""
from hand_runtime.runtime_policy import child_policy_env, runtime_policy

import asyncio
import json
import logging
import os
import time
from contextlib import suppress
from uuid import uuid4
from hand_runtime.process_lease import ProcessLease
from hand_runtime.errors import NodePreparing

LOG = logging.getLogger(__name__)
RECOVERY_DELAYS = (0, 5, 15)


class IsolatedSupervisor:
    def __init__(self, child_module, memory_bytes=None):
        self.child_module = child_module
        self.memory_bytes = memory_bytes
        self.child = None
        self.prepared = False
        self.lock = asyncio.Lock()
        self.warming = None
        self.catalogue = None
        self.lease = ProcessLease()
        self.watchdog_task = None
        self.closed = False
        self.boot = str(uuid4())
        self.operations = {}

    def ready(self):
        return bool(self.prepared and self.child and self.child.returncode is None)

    def schedule_recovery(self):
        """Retry runtime preparation only; never replay a failed engine effect."""
        if self.closed or self.warming is not None and not self.warming.done():
            return
        self.warming = asyncio.create_task(self.recover())

    async def recover(self):
        for attempt, delay in enumerate(RECOVERY_DELAYS, 1):
            if self.closed:
                return
            await asyncio.sleep(delay)
            try:
                await self.warmup()
                return
            except Exception:
                # Native diagnostics can include uploaded names or paths. Keep
                # this operational boundary finite and free of their contents.
                LOG.warning("Analysis metadata preparation failed (attempt %d/%d)",
                            attempt, len(RECOVERY_DELAYS))

    async def stop(self):
        self.prepared = False
        await self.lease.kill()
        for record in self.operations.values():
            if record["state"] == "running":
                record["state"] = "interrupted"
                task = record.get("task")
                if task and task is not asyncio.current_task():
                    task.cancel()
        if self.child:
            with suppress(ProcessLookupError):
                await self.child.wait()
        self.child = None

    @staticmethod
    def outcome(record):
        value = {key: record[key] for key in ("operation_id", "engine", "tool", "state")}
        if "result" in record:
            value["result"] = record["result"]
        return {"content": [{"type": "text", "text": "Analysis operation: " + record["state"]}],
                "structuredContent": value, "isError": False}

    async def exchange(self, name, arguments, permit, *, long=False):
        operation = str(permit.request_uuid)
        payload = json.dumps({"id": operation, "tool": name, "arguments": arguments,
            "expires_at": permit.expires_at}, allow_nan=False).encode() + b"\n"
        if len(payload) > 32768:
            raise ValueError("Bounded analysis command required")
        # A long read here is NOT execution authority. The independent UID
        # watchdog still freezes all native descendants when the lease expires.
        async with asyncio.timeout(runtime_policy().execution_timeout_seconds if long else max(0, permit.expires_at - time.time())):
            self.child.stdin.write(payload)
            await self.child.stdin.drain()
            raw = await self.child.stdout.readline()
            if not raw or len(raw) > 1_000_000 or not long and permit.expires_at <= time.time():
                raise ValueError("Analysis outcome expired or unavailable")
            result = json.loads(raw)
            if (not isinstance(result, dict) or set(result) != {"id", "result"}
                or result["id"] != operation or not isinstance(result["result"], dict)):
                raise ValueError("Bounded correlated analysis result required")
            return result["result"]

    async def run_operation(self, record, arguments, permit):
        try:
            result = await self.exchange("analysis_start", arguments, permit, long=True)
            async with self.lock:
                if record["state"] == "running":
                    record["result"] = result
                    record["state"] = "failed" if result.get("isError") else "completed"
        except asyncio.CancelledError:
            # stop() has already killed the native cohort; never replay it.
            raise
        except Exception:
            async with self.lock:
                await self.stop()
                record["state"] = "failed"
                self.schedule_recovery()

    async def warmup(self):
        async with self.lock:
            if self.ready():
                return
            await self.stop()
            try:
                self.child = await asyncio.create_subprocess_exec("/app/.venv/bin/python", "-m", self.child_module,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    cwd="/app/src", user=1000, group=1000, extra_groups=[], start_new_session=True,
                    env={**child_policy_env(), "PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": "/app/src",
                         "BRIAREUS_PROJECT_TRANSFER":os.environ.get("BRIAREUS_PROJECT_TRANSFER","0"), "HOME": "/home/hand", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                         **({"BRIAREUS_ANALYSIS_MEMORY_BYTES": str(self.memory_bytes)} if self.memory_bytes else {})},
                    limit=1_000_001)
                async with asyncio.timeout(125):
                    raw = await self.child.stdout.readline()
                if not raw or len(raw) > 1_000_000:
                    raise ValueError("Bounded analysis child metadata required")
                first = json.loads(raw)
                if not isinstance(first, dict) or first.get("ready") is not True or set(first) - {"ready", "tools"}:
                    raise ValueError("Analysis child did not prepare its real runtime")
                self.catalogue = first.get("tools")
                self.prepared = True
                if self.watchdog_task is None:
                    self.watchdog_task = asyncio.create_task(self.watchdog())
            except BaseException:
                await self.stop()
                raise

    async def call(self, name, arguments, permit):
        async with self.lock:
            identity = (str(permit.actor_uuid), str(permit.agent_session_uuid), permit.grant_revision)
            if name in {"analysis_poll", "analysis_cancel"}:
                if (set(arguments) != {"operation_id"} or not isinstance(arguments["operation_id"], str)
                    or permit.expires_at <= time.time()):
                    raise ValueError("Current owned analysis operation required")
                record = self.operations.get(self.boot+":"+arguments["operation_id"][8:] if arguments["operation_id"].startswith("request:") else arguments["operation_id"])
                if record is None or record["identity"] != identity:
                    # Reject BEFORE touching the lease: guessed/old IDs never
                    # resume work, including work belonging to another actor.
                    raise ValueError("Analysis operation unavailable for this identity")
                if record["state"] == "running":
                    if name == "analysis_cancel":
                        await self.stop()
                        record["state"] = "cancelled"
                        self.schedule_recovery()
                    else:
                        if not self.ready() or self.lease.identity != identity:
                            raise ValueError("Original prepared analysis runtime required")
                        await self.lease.grant(identity, permit.expires_at)
                return self.outcome(record)
            if any(item["state"] == "running" for item in self.operations.values()):
                raise ValueError("Analysis operation in progress; poll or cancel it first")
            try:
                if permit.expires_at <= time.time():
                    raise ValueError("Current analysis execution authority required")
                if not self.ready():
                    raise NodePreparing()
                prior = self.lease.identity
                preserved = await self.lease.grant(identity, permit.expires_at)
                if prior is not None and not preserved:
                    # A different actor/session/revision never resumes old native
                    # execution. Prepare a clean runtime outside this call.
                    raise NodePreparing()
                if name == "analysis_start":
                    if (set(arguments) != {"engine", "tool", "arguments"}
                        or arguments["engine"] not in {"ghidra", "radare2"}
                        or not isinstance(arguments["tool"], str) or not isinstance(arguments["arguments"], dict)
                        or len(json.dumps(arguments, allow_nan=False).encode()) > 32000):
                        raise ValueError("Exact bounded engine operation required")
                    # Keep at most 32 bounded outcomes in private supervisor
                    # memory. A worker restart invalidates every handle.
                    while len(self.operations) >= 32:
                        self.operations.pop(next(iter(self.operations)))
                    operation_id = self.boot + ":" + str(permit.request_uuid)
                    record = {"operation_id": operation_id, "identity": identity,
                              "engine": arguments["engine"], "tool": arguments["tool"], "state": "running"}
                    self.operations[operation_id] = record
                    record["task"] = asyncio.create_task(self.run_operation(record, arguments, permit))
                    return self.outcome(record)
                return await self.exchange(name, arguments, permit)
            except BaseException:
                await self.stop()
                self.schedule_recovery()
                raise

    async def watchdog(self):
        while True:
            await asyncio.sleep(0.1)
            await self.lease.pause_expired()

    async def close(self):
        self.closed = True
        if self.watchdog_task:
            self.watchdog_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.watchdog_task
        if self.warming:
            self.warming.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.warming
        await self.stop()
