"""Scoped committed owner journal relays; BFF has no owner database access."""
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
import re

from ._panel_events import panel_events

ACCESS_EVENTS = {"session.opened", "session.revoked", "session.revoked_by_parent",
                 "session.elevation_requested", "session.elevation_resolved",
                 "mcp.call.completed", "mcp.call.failed", "mcp.call.unknown"}
PLATFORM_EVENTS = {"team.create", "team.rename", "team.member.add", "team.member.remove",
                   "project.create", "project.rename", "user.link", "inviter.set", "invitation.issue"}
CONNECTION_EVENTS = {"connection.create", "connection.update", "connection.delete",
    "node.register", "node.rename", "node.disable", "node.pair", "node.enable", "node.budget",
    "node.module.publish", "node.runtime_policy", "node.workspace.ensure",
    *("node.module."+phase for phase in ("queued","pulling","stopping","creating","checking",
        "rolling_back","succeeded","failed","unknown"))}


class OwnerSignals:
    def __init__(self, access, platform, resources):
        self.access, self.platform, self.resources = access, platform, resources
        self.windows, self.health = {}, {}
        self.offset = 0

    async def read(self, proof):
        feeds = []
        if self.platform is not None:
            feeds.append(("platform", None))
        projects = [p for p in proof.projects if set(p.permissions)
                    & {"use_resources", "approve_agent_session"}]
        # A bounded fair rotation prevents large memberships from starving the
        # fresh authority snapshot or overflowing an owner's read deadline.
        selected = (projects + projects)[self.offset:self.offset + min(4, len(projects))]
        self.offset = (self.offset + 4) % max(1, len(projects))
        for project in selected:
            if self.access is not None:
                feeds.append(("access", project.project_uuid))
            if self.resources is not None and proof.role == "operator" and "use_resources" in project.permissions:
                feeds.append(("resources", project.project_uuid))
        for source, project in feeds:
            if proof.expires_at <= datetime.now(UTC):
                return
            key = source, str(project)
            state = self.windows.get(key)
            if state is None:
                now = datetime.now(UTC)
                state = {"since": (now - timedelta(hours=23)).isoformat(),
                         "until": now.isoformat(), "after": None}
            try:
                if source == "access":
                    reply = await self.access.for_actor(proof)._call("events.read", proof.user_uuid, project, state)
                elif source == "platform":
                    status, reply = await self.platform.management({"issuer": proof.issuer, "subject": proof.subject,
                        "operation_uuid": str(uuid4()), "action": "events.read", "data": state}, expires_at=proof.expires_at)
                    if status != 200:
                        raise ValueError("Platform event source unavailable")
                else:
                    status, reply = await self.resources.call("/internal/v1/resources/connections", {
                        "issuer": proof.issuer, "subject": proof.subject, "actor_uuid": str(proof.user_uuid),
                        "project_uuid": str(project), "identity_expires_at": proof.expires_at.isoformat(),
                        "action": "events.read", "event_window": state})
                    if status != 200:
                        raise ValueError("Resources event source unavailable")
                if (not isinstance(reply.get("items"), list) or len(reply["items"]) > 128
                    or type(reply.get("truncated")) is not bool):
                    raise ValueError("Invalid owner event page")
                if reply["truncated"]:
                    yield panel_events.resync(source + ".retention")
                allowed = {"access": ACCESS_EVENTS, "platform": PLATFORM_EVENTS, "resources": CONNECTION_EVENTS}[source]
                for item in reply["items"]:
                    if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                        raise ValueError("Invalid owner event envelope")
                    mcp_call = source == "access" and item["type"].startswith("mcp.call.")
                    keys = {"event_id", "type", "occurredAt", "actor_id", "project_id", "operation_id", "entity_id"}
                    if mcp_call: keys.add("call")
                    if (set(item) != keys
                        or source != "platform" and item["project_id"] != str(project)):
                        raise ValueError("Invalid owner event binding")
                    if item["type"] not in allowed:
                        # Do not interpret a future event's entity selector as
                        # an old UUID contract or publish unknown metadata.
                        yield panel_events.resync(source + ".event_contract")
                        continue
                    for name in ("event_id", "actor_id", "project_id", "operation_id", "entity_id"):
                        if name == "entity_id" and source == "resources" and item["type"] == "node.runtime_policy":
                            entity = item[name]
                            if entity != "server" and (not isinstance(entity, str) or not entity.startswith("node:")
                                or str(UUID(entity[5:])) != entity[5:]):
                                raise ValueError("Invalid runtime policy selector")
                            continue
                        if item[name] is not None and str(UUID(item[name])) != item[name]:
                            raise ValueError("Invalid owner event identifier")
                    if datetime.fromisoformat(item["occurredAt"]).tzinfo is None:
                        raise ValueError("Invalid owner event time")
                    if mcp_call:
                        call = item["call"]
                        if (not isinstance(call, dict) or set(call) != {"hand", "tool", "status", "session_uuid", "node_uuid", "placement_uuid", "duration_ms", "transport"}
                            or call["hand"] not in {"files", "terminal", "web", "svc", "infrastructure", "reverse", "serena"}
                            or not isinstance(call["tool"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", call["tool"])
                            or call["status"] != item["type"].removeprefix("mcp.call.")
                            or type(call["duration_ms"]) is not int or not 0 <= call["duration_ms"] <= 86400000
                            or call["transport"] != "gateway-mcp"):
                            raise ValueError("Invalid call metadata")
                        for identifier in ("session_uuid", "node_uuid", "placement_uuid"):
                            if str(UUID(call[identifier])) != call[identifier]: raise ValueError("Invalid call binding")
                    if source == "access":
                        visibility = {"kind": "access", "project": str(project), "actor": item["actor_id"]}
                    elif source == "platform":
                        visibility = {"kind": "operator"} if proof.role=='operator' else {"kind":"actor","id":str(proof.user_uuid)}
                    else:
                        visibility = {"kind": "project_operator", "id": str(project)}
                    await panel_events.emit("mcp.calls" if mcp_call else "access.sessions" if source == "access" else "management.events",
                        item["type"].removeprefix("mcp.") if mcp_call else item["type"],
                        {**item, **(item["call"] if mcp_call else {}), "source": source}, visibility=visibility,
                        event_id=source + ":" + item["event_id"] + (":"+str(proof.user_uuid) if source=='platform' and proof.role!='operator' else ''), occurred_at=item["occurredAt"])
                after = reply.get("next")
                if after is not None:
                    if not isinstance(after, list) or len(after) != 2:
                        raise ValueError("Invalid owner continuation")
                    datetime.fromisoformat(after[0]); UUID(after[1])
                    state = {**state, "after": after}
                else:
                    state = {"since": (datetime.fromisoformat(state["until"]) - timedelta(minutes=5)).isoformat(),
                             "until": datetime.now(UTC).isoformat(), "after": None}
                self.windows[key] = state
                if self.health.get(key) is not True:
                    yield self.source_notice(source, project,
                        "source.recovered" if self.health.get(key) is False else "source.connected")
                self.health[key] = True
            except Exception:
                if self.health.get(key) is not False:
                    yield self.source_notice(source, project, "source.unavailable")
                self.health[key] = False

    @staticmethod
    def source_notice(source, project, kind):
        return {"topic": "system.notifications", "type": kind,
                "occurredAt": datetime.now(UTC).isoformat(),
                "data": {"source": source, "project_id": str(project) if project else None}}
