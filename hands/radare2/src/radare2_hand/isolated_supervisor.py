"""Trusted rootless parent; native parsers never share its UID or memory."""
import asyncio
import json
import time
from contextlib import suppress
from hand_runtime.process_lease import ProcessLease


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

    def ready(self):
        return bool(self.prepared and self.child and self.child.returncode is None)

    async def stop(self):
        self.prepared = False
        await self.lease.kill()
        if self.child:
            with suppress(ProcessLookupError):
                await self.child.wait()
        self.child = None

    async def warmup(self):
        async with self.lock:
            if self.ready():
                return
            await self.stop()
            try:
                self.child = await asyncio.create_subprocess_exec("/app/.venv/bin/python", "-m", self.child_module,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    cwd="/app/src", user=1000, group=1000, extra_groups=[], start_new_session=True,
                    env={"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": "/app/src",
                         "HOME": "/home/hand", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
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
            try:
                if not self.ready() or permit.expires_at <= time.time():
                    raise ValueError("Current prepared analysis runtime required")
                identity = (str(permit.actor_uuid), str(permit.agent_session_uuid), permit.grant_revision)
                prior = self.lease.identity
                preserved = await self.lease.grant(identity, permit.expires_at)
                if prior is not None and not preserved:
                    # A different actor/session/revision never resumes old native
                    # execution. Prepare a clean runtime outside this call.
                    raise ValueError("Native execution identity changed; clean warmup required")
                operation = str(permit.request_uuid)
                payload = json.dumps({"id": operation, "tool": name, "arguments": arguments,
                    "expires_at": permit.expires_at}, allow_nan=False).encode() + b"\n"
                if len(payload) > 32768:
                    raise ValueError("Bounded analysis command required")
                async with asyncio.timeout(max(0, permit.expires_at - time.time())):
                    self.child.stdin.write(payload)
                    await self.child.stdin.drain()
                    raw = await self.child.stdout.readline()
                    if not raw or len(raw) > 1_000_000 or permit.expires_at <= time.time():
                        raise ValueError("Analysis outcome expired or unavailable")
                    result = json.loads(raw)
                    if (not isinstance(result, dict) or set(result) != {"id", "result"}
                        or result["id"] != operation or not isinstance(result["result"], dict)):
                        raise ValueError("Bounded correlated analysis result required")
                    return result["result"]
            except BaseException:
                await self.stop()
                self.warming = asyncio.create_task(self.warmup())
                self.warming.add_done_callback(lambda task: None if task.cancelled() else task.exception())
                raise

    async def watchdog(self):
        while True:
            await asyncio.sleep(0.1)
            await self.lease.pause_expired()

    async def close(self):
        if self.watchdog_task:
            self.watchdog_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.watchdog_task
        if self.warming:
            self.warming.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.warming
        await self.stop()
