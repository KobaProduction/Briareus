"""Trusted Node parent; Serena and all LSP descendants have a separate UID."""
from __future__ import annotations
from hand_runtime.runtime_policy import child_policy_env, runtime_policy

import asyncio
import json
import time
from contextlib import suppress
from hand_runtime.process_lease import ProcessLease
from hand_runtime.deferred_calls import DeferredCalls


class SerenaSupervisor:
    def __init__(self, project_path):
        self.project_path = project_path
        self.lease = ProcessLease(1000)
        self.child = None
        self.prepared = False
        self.catalogue = None
        self.lock = asyncio.Lock()
        self.warming = None
        self.watchdog_task = None
        self.deferred = DeferredCalls('serena',lock=self.lock,lease=self.lease,ready=self.ready,
            tools=lambda:{item['name'] for item in self.catalogue or []},execute=self.exchange_background,
            stop=self.stop,recover=self._schedule_warmup)

    def ready(self):
        return bool(self.prepared and self.child is not None and self.child.returncode is None)

    async def stop(self):
        self.prepared = False
        self.deferred.interrupt()
        await self.lease.kill()
        if self.child is not None:
            with suppress(ProcessLookupError):
                await self.child.wait()
        self.child = None

    async def warmup(self):
        async with self.lock:
            if self.ready():
                return
            await self.stop()
            try:
                self.child = await asyncio.create_subprocess_exec(
                    "/opt/serena/.venv/bin/python", "-m", "serena_hand.isolated_child",
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    cwd="/app/src", user=1000, group=1000, extra_groups=[], start_new_session=True,
                    env={**child_policy_env(), "PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": "/app/src",
                         "HOME": "/home/hand", "SERENA_HOME": "/home/hand/.serena",
                         "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                         "BRIAREUS_SERENA_PROJECT_PATH": self.project_path,
                         "UV_OFFLINE": "1", "UV_PYTHON_DOWNLOADS": "never", "MALLOC_ARENA_MAX": "2"},
                    limit=1000001)
                async with asyncio.timeout(180):
                    raw = await self.child.stdout.readline()
                if not raw or len(raw) > 1000000:
                    raise ValueError("Bounded actual Serena metadata required")
                first = json.loads(raw)
                if (not isinstance(first, dict) or set(first) != {"ready", "tools"}
                    or first["ready"] is not True or not isinstance(first["tools"], list)
                    or not 0 < len(first["tools"]) <= 512):
                    raise ValueError("Actual Serena runtime readiness required")
                if self.catalogue is not None and first["tools"] != self.catalogue:
                    raise ValueError("Immutable Serena tool catalogue changed")
                self.catalogue = first["tools"]
                self.prepared = True
                if self.watchdog_task is None:
                    self.watchdog_task = asyncio.create_task(self.watchdog())
            except BaseException:
                await self.stop()
                raise

    def _schedule_warmup(self):
        if self.warming is not None and not self.warming.done():
            return
        self.warming = asyncio.create_task(self.warmup())
        self.warming.add_done_callback(lambda task: None if task.cancelled() else task.exception())

    async def call(self, name, arguments, permit):
        async with self.lock:
            identity = (str(permit.actor_uuid), str(permit.agent_session_uuid), permit.grant_revision)
            if name in {'serena_operation_poll','serena_operation_cancel'}:
                return await self.deferred.control(name,arguments,permit,identity)
            if self.deferred.running():
                raise ValueError('Serena operation in progress; poll or cancel it first')
            try:
                if not self.ready() or permit.expires_at <= time.time():
                    raise ValueError("Prepared actual Serena runtime and current authority required")
                previous = self.lease.identity
                preserved = await self.lease.grant(identity, permit.expires_at)
                if previous is not None and not preserved:
                    # Changing principal must never inherit another agent's LSP/session state.
                    # The failed call was never dispatched; the next request uses a fresh child.
                    raise ValueError("Serena identity changed; preparing a fresh isolated session")
                if name=='serena_operation_start':
                    return await self.deferred.start(arguments,permit,identity)
                return await self.exchange(name,arguments,permit)
            except BaseException:
                # A timed-out request is never replayed after resuming a process.
                await self.stop()
                self._schedule_warmup()
                raise

    async def exchange_background(self,name,arguments,permit):
        return await self.exchange(name,arguments,permit,background=True)

    async def exchange(self,name,arguments,permit,*,background=False):
        operation=str(permit.request_uuid)
        command={'id':operation,'tool':name,'arguments':arguments,'expires_at':permit.expires_at}
        if background:command['background']=True
        payload=json.dumps(command,allow_nan=False).encode()+b'\n'
        if len(payload)>32768:raise ValueError('Bounded exact Serena command required')
        # Waiting for IPC is not authority: the UID watchdog still stops all
        # native descendants after the short grant, including LSP processes.
        async with asyncio.timeout(None if background else max(0,permit.expires_at-time.time())):
            self.child.stdin.write(payload)
            await self.child.stdin.drain()
            raw=await self.child.stdout.readline()
        if not raw or len(raw)>1000000 or not background and permit.expires_at<=time.time():
            raise ValueError('Serena result expired or unavailable')
        result=json.loads(raw)
        if (not isinstance(result,dict) or set(result)!={'id','result'}
            or result['id']!=operation or not isinstance(result['result'],dict)):
            raise ValueError('Correlated original Serena MCP result required')
        return result['result']

    async def watchdog(self):
        while True:
            await asyncio.sleep(0.05)
            try:
                await self.lease.pause_expired()
            except Exception:
                async with self.lock:
                    await self.stop()
                    self._schedule_warmup()

    async def close(self):
        if self.watchdog_task is not None:
            self.watchdog_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.watchdog_task
        if self.warming is not None:
            self.warming.cancel()
            with suppress(asyncio.CancelledError):
                await self.warming
        await self.stop()
