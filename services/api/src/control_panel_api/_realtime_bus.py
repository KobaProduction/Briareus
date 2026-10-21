"""HTTP Bridge RealtimeBus port: Valkey fanout, topic snapshots and replay.

Unlike the old global admin channel, every envelope carries an explicit
visibility scope and is filtered against current Platform membership.
Only committed operation metadata is accepted; credentials/results/arguments
are never event payloads. Redis streams supplement the original Pub/Sub bus.
"""
import asyncio
import json
import logging
import resource
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from valkey.exceptions import ValkeyError

REALTIME_TOPICS = frozenset({"mcp.calls", "system.metrics", "system.notifications",
                            "browser.runtime", "management.events", "platform.context", "access.sessions"})
_CHANNEL = "briareus:panel:events:fanout"
_JOURNAL = "briareus:panel:events:journal"


class PanelEvents:
    def __init__(self):
        self.listeners = set()
        self.client = None
        self.task = None
        self.pubsub = None
        self.metrics_task = None
        self.started_at = time.monotonic()

    async def start(self, client):
        self.client = client
        self.pubsub = client.pubsub(ignore_subscribe_messages=True)
        try:
            await self.pubsub.subscribe(_CHANNEL)
        except ValkeyError:
            logging.getLogger(__name__).warning("realtime broker unavailable at startup")
        self.task = asyncio.create_task(self._listen(), name="panel-realtime-fanout")
        self.metrics_task = asyncio.create_task(self._metrics(), name="panel-realtime-metrics")

    async def close(self):
        if self.metrics_task:
            self.metrics_task.cancel()
            await asyncio.gather(self.metrics_task, return_exceptions=True)
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.pubsub:
            await self.pubsub.aclose()
        self.task = self.pubsub = self.client = None

    async def _metrics(self):
        while True:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            await self.emit("system.metrics", "process.snapshot", {
                "source": "control-panel-api", "uptime_seconds": round(time.monotonic()-self.started_at),
                "cpu_user_seconds": usage.ru_utime, "cpu_system_seconds": usage.ru_stime,
                "peak_memory_kib": usage.ru_maxrss}, visibility={"kind": "operator"})
            await asyncio.sleep(10)

    @asynccontextmanager
    async def subscribe(self):
        queue = asyncio.Queue(maxsize=256)
        self.listeners.add(queue)
        try:
            yield queue
        finally:
            self.listeners.discard(queue)

    def _fanout(self, event):
        for queue in tuple(self.listeners):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({"topic": "system.notifications", "type": "resync.required",
                                  "scope": {"kind": "broadcast"}, "data": {},
                                  "occurredAt": datetime.now(UTC).isoformat()})
            queue.put_nowait(event)

    async def _listen(self):
        while True:
            try:
                message = await self.pubsub.get_message(timeout=1)
                if message and isinstance(message.get("data"), str) and len(message["data"]) <= 16384:
                    event = json.loads(message["data"])
                    if isinstance(event, dict) and event.get("topic") in REALTIME_TOPICS:
                        self._fanout(event)
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                raise
            except (ValkeyError, ValueError, TypeError):
                logging.getLogger(__name__).warning("realtime broker reconnecting")
                await asyncio.sleep(1)
                try:
                    await self.pubsub.subscribe(_CHANNEL)
                except ValkeyError:
                    pass

    @staticmethod
    def resync(reason):
        return {"topic": "system.notifications", "type": "resync.required",
                "occurredAt": datetime.now(UTC).isoformat(), "data": {"reason": reason},
                "scope": {"kind": "broadcast"}}

    async def emit(self, topic, event_type, data, *, visibility, event_id=None, occurred_at=None):
        if topic not in REALTIME_TOPICS or not isinstance(data, dict):
            raise ValueError("Supported scoped event required")
        event = {"version": 1, "event_id": event_id or str(uuid4()), "topic": topic, "type": event_type,
                 "occurredAt": occurred_at or datetime.now(UTC).isoformat(), "data": data, "scope": visibility}
        encoded = json.dumps(event, separators=(",", ":"))
        if len(encoded) > 8192:
            raise ValueError("Event metadata too large")
        if self.client is None:
            self._fanout(event)
            return
        try:
            await self.client.eval(
                "if ARGV[2]~='' and redis.call('EXISTS',KEYS[3])==1 then return '' end "
                "local id=redis.call('XADD',KEYS[1],'MAXLEN',20000,'*','event',ARGV[1]); "
                "local event=cjson.decode(ARGV[1]); event.cursor=id; "
                "redis.call('PUBLISH',KEYS[2],cjson.encode(event)); "
                "if ARGV[2]~='' then redis.call('SET',KEYS[3],id,'EX',90000) end return id", 3,
                _JOURNAL, _CHANNEL, _JOURNAL + ':seen:' + (event_id or 'ephemeral'), encoded, event_id or '')
        except ValkeyError:
            logging.getLogger(__name__).warning("realtime event broker unavailable")
            self._fanout(event)

    @staticmethod
    def visible(event, proof):
        scope = event.get("scope", {})
        kind = scope.get("kind")
        return (kind == "broadcast" or kind == "operator" and proof.role == "operator"
                or kind == "actor" and scope.get("id") == str(proof.user_uuid)
                or kind == "project_operator" and proof.role == "operator"
                    and scope.get("id") in {str(p.project_uuid) for p in proof.projects}
                or kind == "access" and any(str(p.project_uuid) == scope.get("project")
                    and (scope.get("actor") == str(proof.user_uuid)
                         or "approve_agent_session" in p.permissions) for p in proof.projects)
                or kind == "project" and scope.get("id") in {str(p.project_uuid) for p in proof.projects})

    async def replay(self, *, proof, topics, cursor=None):
        if self.client is None:
            return [self.resync("broker.unavailable")]
        try:
            events = []
            if cursor:
                earliest = await self.client.xrange(_JOURNAL, count=1)
                latest = await self.client.xrevrange(_JOURNAL, count=1)
                number = lambda item: tuple(map(int, item.split("-")))
                if (not earliest or number(cursor) < number(earliest[0][0])
                    or number(cursor) > number(latest[0][0])):
                    events.append(self.resync("journal.retention"))
                rows = await self.client.xrange(_JOURNAL, min="(" + cursor, max="+", count=2001)
                if len(rows) > 2000:
                    events.append(self.resync("journal.backlog"))
                    rows = rows[-2000:]
            else:
                rows = list(reversed(await self.client.xrevrange(_JOURNAL, count=200)))
            for event_id, fields in rows:
                event = json.loads(fields["event"])
                if event.get("topic") in topics and self.visible(event, proof):
                    event["cursor"] = event_id
                    events.append(event)
            return events
        except (ValkeyError, ValueError, KeyError):
            return [self.resync("broker.unavailable")]

    async def history(self, *, proof, topics, before=None, project=None, limit=100):
        """Read an older scoped page; cursor advances over invisible rows too."""
        if self.client is None:
            raise ValueError("JOURNAL_UNAVAILABLE")
        allowed = {str(item.project_uuid) for item in proof.projects}
        if project is not None and project not in allowed:
            raise ValueError("JOURNAL_PROJECT_DENIED")
        items, scanned, cursor = [], 0, before
        maximum = "(" + before if before else "+"
        # Scan is bounded independently of visible count. A sparse page may be
        # empty with has_more=true; consumers must continue using next_cursor.
        async with asyncio.timeout(5):
            while len(items) < limit and scanned < 2000:
                rows = await self.client.xrevrange(_JOURNAL, max=maximum, count=min(200, 2000-scanned))
                if not rows:
                    break
                for event_id, fields in rows:
                    scanned += 1
                    cursor = event_id
                    event = json.loads(fields["event"])
                    payload = event.get("data", {})
                    if (event.get("topic") in topics and self.visible(event, proof)
                        and (project is None or payload.get("project_id") == project)):
                        event["cursor"] = event_id
                        items.append(event)
                    if len(items) == limit:
                        break
                maximum = "(" + cursor
            more = bool(cursor and await self.client.xrevrange(_JOURNAL, max="("+cursor, count=1))
            first = await self.client.xrange(_JOURNAL, count=1)
        expired = bool(before and first and tuple(map(int, before.split("-"))) < tuple(map(int, first[0][0].split("-"))))
        return {"items": items, "next_cursor": cursor if more else None, "has_more": more,
                "retention_gap": expired, "retention_limit": 20000}

    async def publish(self, *, actor, project, hand, tool, operation, status, duration_ms):
        visibility = {"kind": "project", "id": str(project)}
        await self.emit("mcp.calls", "call." + status, {
            "actor_id": str(actor), "project_id": str(project), "hand": hand,
            "tool": tool, "operation_id": str(operation), "status": status,
            "duration_ms": duration_ms, "transport": "panel-owner-rpc"}, visibility=visibility)
        if hand == "web":
            await self.emit("browser.runtime", "operation." + status,
                {"project_id": str(project), "operation_id": str(operation), "tool": tool,
                 "status": status}, visibility=visibility)
