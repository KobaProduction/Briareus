"""Prepared provider process, reused only within one current agent identity.

The UID-separated child never receives Core credentials. Each call supplies
fresh owner context; a five-second ProcessLease freezes every child descendant
when authority expires. Identity/revision changes destroy the entire cohort.
"""
from __future__ import annotations

from hand_runtime.runtime_policy import child_policy_env, runtime_policy

import asyncio
from contextlib import suppress
import json
import os
import time

from .process_lease import ProcessLease


class ProviderSupervisor:
    def __init__(self, module):
        if module not in {"svc", "infrastructure"}:
            raise ValueError("Approved provider module required")
        self.module = module
        self.lease = ProcessLease(1000)
        self.child = None
        self.prepared = False
        self.lock = asyncio.Lock()
        self.warming = None
        self.watchdog_task = None
        from .deferred_calls import DeferredCalls
        self.tools=set()
        self.active_context={}
        self.deferred=DeferredCalls(module,lock=self.lock,lease=self.lease,ready=self.ready,
            tools=lambda:self.tools,execute=self.exchange_background,stop=self.stop,recover=self._schedule_warmup)

    def ready(self):
        return bool(self.prepared and self.child is not None and self.child.returncode is None)

    async def stop(self):
        self.prepared = False
        self.active_context={}
        self.deferred.interrupt()
        await self.lease.kill()
        if self.child is not None:
            await self.child.wait()
        self.child = None

    async def warmup(self):
        async with self.lock:
            if self.ready():
                return
            await self.stop()
            env = {**child_policy_env(), "PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": "/app/src",
                   "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                   "HOME": "/home/hand", "GIT_TERMINAL_PROMPT": "0",
                   "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                   "MALLOC_ARENA_MAX": "2"}
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                        "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
                if key in os.environ:
                    env[key] = os.environ[key]
            try:
                self.child = await asyncio.create_subprocess_exec(
                    "/app/.venv/bin/python", "-m", self.module + "_hand.isolated_child",
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, cwd="/app/src", env=env,
                    user=1000, group=1000, extra_groups=[], start_new_session=True, limit=1000001)
                async with asyncio.timeout(120):
                    raw = await self.child.stdout.readline()
                if len(raw) > 64 or json.loads(raw) != {"ready": True}:
                    raise ValueError("Provider metadata preparation failed")
                self.prepared = True
                if self.watchdog_task is None:
                    self.watchdog_task = asyncio.create_task(self.watchdog())
            except BaseException:
                await self.stop()
                raise

    def _schedule_warmup(self):
        if self.warming is not None and not self.warming.done():return
        self.warming = asyncio.create_task(self.warmup())
        self.warming.add_done_callback(lambda task: None if task.cancelled() else task.exception())

    @staticmethod
    def context_digest(context):
        import hashlib
        return hashlib.sha256(json.dumps(context,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

    async def execute(self, name, arguments, permit, context):
        if (not isinstance(context,dict) or set(context)-{"accounts","policies"} or not isinstance(context.get("accounts"),list)):
            raise ValueError("Current project credential owner context required")
        async with self.lock:
            identity=(str(permit.actor_uuid),str(permit.agent_session_uuid),permit.grant_revision)
            if name in {self.module+"_operation_poll",self.module+"_operation_cancel"}:
                record=self.deferred.lookup(arguments.get("operation_id", ""))
                if record is None or record.get("account_id")!=arguments.get("account_id") or record["tool"]!=arguments.get("tool") or record.get("provider")!=arguments.get("provider"):
                    raise ValueError("Exact original provider account required")
                if record['identity']!=identity:
                    raise ValueError("Original provider identity required")
                if name.endswith("_poll") and record.get("context_digest")!=self.context_digest(context):
                    await self.stop();self._schedule_warmup()
                    raise ValueError("Provider connection or policy changed; operation interrupted")
                return await self.deferred.control(name,{key:value for key,value in arguments.items() if key not in {"account_id","provider"} and (not name.endswith("_cancel") or key!="tool")},permit,identity)
            if self.deferred.running():raise ValueError("Operation in progress; poll or cancel")
            try:
                if not self.ready() or permit.expires_at<=time.time():raise ValueError("Current prepared provider required")
                previous=self.lease.identity
                preserved=await self.lease.grant(identity,permit.expires_at)
                if previous is not None and not preserved:raise ValueError("Fresh provider identity preparation required")
                if name==self.module+"_operation_start":
                    self.active_context=context
                    result=await self.deferred.start(arguments,permit,identity)
                    record=self.deferred.records[result["structuredContent"]["operation_id"]]
                    record["account_id"]=arguments["arguments"].get("account_id")
                    record["provider"]=arguments["arguments"].get("provider")
                    record["context_digest"]=self.context_digest(context)
                    return result
                return await self.exchange(name,arguments,permit,context)
            except BaseException:
                await self.stop();self._schedule_warmup();raise

    async def exchange_background(self,name,arguments,permit):
        try:return await self.exchange(name,arguments,permit,self.active_context,background=True)
        finally:self.active_context={}

    async def exchange(self,name,arguments,permit,context,*,background=False):
        payload=json.dumps({"id":str(permit.request_uuid),"tool":name,"arguments":arguments,"context":context,
            "expires_at":permit.expires_at,"background":background},ensure_ascii=True,allow_nan=False).encode()+b"\n"
        if len(payload)>131072:raise ValueError("Bounded provider request required")
        async with asyncio.timeout(None if background else max(0,permit.expires_at-time.time())):
            self.child.stdin.write(payload);await self.child.stdin.drain();raw=await self.child.stdout.readline()
        if not raw or len(raw)>1000000 or not background and permit.expires_at<=time.time():raise ValueError("Current provider result unavailable")
        result=json.loads(raw)
        if not isinstance(result,dict) or set(result)!={"id","result"} or result["id"]!=str(permit.request_uuid) or not isinstance(result["result"],dict):
            raise ValueError("Correlated provider outcome required")
        return result["result"]

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
        for task in (self.watchdog_task, self.warming):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        await self.stop()
