"""Single-writer node reconciler, called only after authenticated Core admission.

No shell, host Docker fallback, all-service restart, volume deletion or automatic
MCP effect retry. The node Gateway closes a placement while its operation runs.
"""
from __future__ import annotations

import asyncio
import re
from uuid import UUID

from node_protocol import Deployment, NodeRecord, ResourceLimits

from .docker_engine import DEPLOYMENT_LABEL, SPEC_LABEL, DockerEngine, EngineFailure
from .journal import Journal, OperationConflict, TERMINAL
from .planner import Instance, plan
from .diagnostics import state_diagnostic


class Controller:
    def __init__(self, node: NodeRecord, engine: DockerEngine, journal: Journal):
        self.node, self.engine, self.journal = node, engine, journal
        # Serializes admission and capacity accounting across placements.
        self.lock = asyncio.Lock()

    async def observed(self) -> list[Instance]:
        from .runtime_profiles import ROLE_LABEL, EGRESS_REQUIRED, EGRESS_MEMORY, EGRESS_CPU, EGRESS_PIDS
        from .egress_runtime import companion_name
        result, mains, helpers = [], [], {}
        for item in await self.engine.containers(self.node.id):
            current = await self.engine.inspect(item["Id"])
            if current is None:
                continue
            metadata = current.get("Config",{}).get("Labels",{})
            host = current.get("HostConfig",{})
            try:
                limits = ResourceLimits(memory_bytes=host["Memory"],
                    cpu_millis=host["NanoCpus"]//1_000_000,pids=host["PidsLimit"])
                placement = UUID(metadata[DEPLOYMENT_LABEL])
                fingerprint = metadata[SPEC_LABEL]
                if placement.version!=4 or not re.fullmatch(r"[a-f0-9]{64}",fingerprint):
                    raise ValueError("Invalid managed instance")
                role = metadata.get(ROLE_LABEL)
                if role not in (None,"egress"):
                    raise ValueError("Unknown execution component")
                if role=="egress":
                    if (limits.memory_bytes!=EGRESS_MEMORY or limits.cpu_millis!=EGRESS_CPU
                        or limits.pids!=EGRESS_PIDS or host.get("Binds") or host.get("Mounts")
                        or host.get("Privileged") or host.get("ReadonlyRootfs") is not True
                        or current.get("Config",{}).get("User")!="1000:1000"):
                        raise ValueError("Unverified isolated egress budget")
                    name = current["Name"].removeprefix("/")
                    if name in helpers:
                        raise ValueError("Duplicate placement egress")
                    helpers[name] = (current,limits)
                else:
                    mains.append((current,placement,fingerprint,limits))
            except (ValueError,KeyError,TypeError):
                raise EngineFailure("Managed instance has unverified resource configuration") from None
        for current,placement,fingerprint,limits in mains:
            state = current["State"]
            running = state.get("Running") is True
            ready = state.get("Health",{}).get("Status")=="healthy"
            if current["Config"]["Labels"].get(EGRESS_REQUIRED)=="true":
                name = companion_name(current["Name"].removeprefix("/"))
                helper = helpers.pop(name,None)
                if helper:
                    peer,quota = helper
                    metadata = peer["Config"]["Labels"]
                    if metadata[DEPLOYMENT_LABEL]!=str(placement) or metadata[SPEC_LABEL]!=fingerprint:
                        raise EngineFailure("Egress component belongs to a different placement revision")
                    limits = ResourceLimits(memory_bytes=limits.memory_bytes+quota.memory_bytes,
                        cpu_millis=limits.cpu_millis+quota.cpu_millis,pids=limits.pids+quota.pids)
                    running = running and peer["State"].get("Running") is True
                    ready = ready and peer["State"].get("Health",{}).get("Status")=="healthy"
                else:
                    # Reserve the full missing helper budget too. A broken
                    # component cannot accidentally free capacity for another.
                    limits = ResourceLimits(memory_bytes=limits.memory_bytes+EGRESS_MEMORY,
                        cpu_millis=limits.cpu_millis+EGRESS_CPU,pids=limits.pids+EGRESS_PIDS)
                    running = ready = False
            result.append(Instance(current["Id"],placement,fingerprint,limits,running,ready))
        for peer,quota in helpers.values():
            # Interrupted creation must remain accounted and visibly blocked.
            # Never silently adopt an orphan as a healthy complete module.
            metadata = peer["Config"]["Labels"]
            result.append(Instance(peer["Id"],UUID(metadata[DEPLOYMENT_LABEL]),metadata[SPEC_LABEL],
                                   quota,False,False))
        return result

    async def wait_ready(self, container: str):
        # Cold imports in Python Hands are CPU-throttled by the placement's
        # explicit quota; 0.1 CPU must not produce a false startup failure.
        async with asyncio.timeout(180):
            while True:
                current = await self.engine.inspect(container)
                state = current.get("State", {}) if current else {}
                if not state.get("Running") or state.get("Health", {}).get("Status") == "unhealthy":
                    raise EngineFailure("Target failed readiness", diagnostic=state_diagnostic("checking", state))
                if state.get("Health", {}).get("Status") == "healthy":
                    complete = [item for item in await self.observed() if item.container_id==container]
                    if len(complete)==1 and complete[0].ready:
                        return
                await asyncio.sleep(1)

    async def observe_completion(self,operation,sequence):
        """Finalize a lost checking receipt from fresh exact native inventory only.

        Called by the signed Core Operation RPC. Never starts, stops, pulls or
        replaces a container and never resumes a user MCP process lease.
        """
        async with self.lock:
            receipt=self.journal.get(operation)
            if receipt is None or receipt["sequence"]!=sequence or receipt["phase"]!="checking":
                return receipt
            desired=Deployment.model_validate_json(receipt["desired"])
            if not self.node.enabled or not desired.enabled or desired.node_uuid!=self.node.id:return receipt
            await self.engine.verify_rootless()
            observed=await self.observed()
            own=[item for item in observed if item.deployment_uuid==desired.id]
            if (len(own)==1 and own[0].container_id==receipt["container"] and own[0].fingerprint==desired.fingerprint
                and own[0].limits==desired.limits and own[0].running and own[0].ready
                and self.node.budget.fits([item.limits for item in observed])):
                self.journal.applied(operation,desired,own[0].container_id)
            return self.journal.get(operation)

    async def apply(self, operation: UUID, sequence: int, desired: Deployment):
        if desired.node_uuid != self.node.id or not self.node.enabled or not desired.enabled:
            raise OperationConflict("Enabled placement on the exact enrolled node required")
        async with self.lock:
            if not self.node.enabled:
                raise OperationConflict("Node admission was disabled while waiting")
            receipt = self.journal.reserve(operation, sequence, desired)
            if receipt["phase"] in TERMINAL:
                return receipt
            previous = Deployment.model_validate_json(receipt["previous"]) if receipt["previous"] else None
            if previous and previous.project_uuid != desired.project_uuid:
                raise OperationConflict("A placement cannot change project ownership")
            if previous and (previous.workspace.id if previous.workspace else None) != (
                desired.workspace.id if desired.workspace else None):
                raise OperationConflict("Storage relocation requires a separate placement operation")
            if receipt["phase"] == "rolling_back":
                await self.rollback(operation, previous, desired)
                return self.journal.get(operation)
            try:
                await self.engine.verify_rootless()
                observed = await self.observed()
                own = [item for item in observed if item.deployment_uuid == desired.id]
                if (len(own) == 1 and not own[0].ready
                    and own[0].fingerprint == desired.fingerprint
                    and own[0].limits == desired.limits
                    and self.journal.matches_applied(desired, own[0].container_id)
                    and self.node.budget.fits([item.limits for item in observed])):
                    # An explicit fresh Core operation can repair the exact
                    # retained applied instance. Never adopt a merely labelled
                    # foreign/failed candidate or replay an MCP tool effect.
                    self.journal.phase(operation, "checking", container=own[0].container_id)
                    container = await self.engine.resume_applied(desired)
                    await self.wait_ready(container)
                    self.journal.applied(operation, desired, container)
                    return self.journal.get(operation)
                action = plan(self.node, desired, observed)
                target = [item for item in observed if item.deployment_uuid == desired.id]
                matching = [item for item in target if item.fingerprint == desired.fingerprint]
                failed_candidate=(len(target)==1 and self.journal.failed_candidate(desired,
                    target[0].container_id,target[0].fingerprint,sequence))
                if action.action=="blocked" and failed_candidate and not target[0].ready:
                    # A new signed Core operation may replace its own journaled
                    # failed candidate. Unknown/foreign processes stay blocked.
                    action=plan(self.node,desired,[item for item in observed if item not in target])
                    matching=[]
                if action.action == "keep":
                    self.journal.applied(operation, desired, target[0].container_id)
                    return self.journal.get(operation)
                recovering = (receipt["phase"] in {"creating", "checking"}
                              and len(target) == len(matching) == 1 and matching[0].running)
                if action.action in {"blocked", "disabled"} and not recovering:
                    raise EngineFailure(action.reason)
                # Without a retained previous configuration, never delete an
                # unknown existing process just because its labels look familiar.
                if target and previous is None and not failed_candidate and not (
                    recovering and receipt["container"] == target[0].container_id
                ):
                    self.journal.phase(operation, "failed", error="UNMANAGED_INSTANCE")
                    return self.journal.get(operation)
                # A controller may have exited after create/start, before its
                # final receipt. Resume readiness; never stop a matching instance.
                if matching:
                    container = matching[0].container_id
                else:
                    self.journal.phase(operation, "pulling")
                    await self.engine.pull(desired)
                    self.journal.phase(operation, "stopping")
                    for item in target:
                        await self.engine.remove_target(desired, item.container_id)
                    self.journal.phase(operation, "creating")
                    container = await self.engine.stage(desired)
                self.journal.phase(operation, "checking", container=container)
                await self.wait_ready(container)
                self.journal.applied(operation, desired, container)
            except (EngineFailure, TimeoutError) as failure:
                receipt = self.journal.get(operation)
                diagnostic = getattr(failure, "diagnostic", None)
                if diagnostic is None and getattr(failure, "reason", None):
                    diagnostic = {"stage":receipt["phase"],"component":"engine","reason":failure.reason}
                if diagnostic is None:
                    diagnostic = await self.failure_diagnostic(receipt, desired, timeout=isinstance(failure, TimeoutError))
                self.journal.phase(operation, receipt["phase"], diagnostic=diagnostic)
                await self.rollback(operation, previous, desired)
            return self.journal.get(operation)

    async def failure_diagnostic(self, receipt, desired, *, timeout=False):
        stage = receipt["phase"]
        if stage == "pulling":
            return {"stage":stage,"component":"engine","reason":"pull_failed"}
        try:
            current = await self.engine.inspect(receipt["container"]) if receipt.get("container") else None
            if current:
                metadata = current.get("Config", {}).get("Labels", {})
                if (metadata.get(DEPLOYMENT_LABEL) == str(desired.id)
                    and metadata.get(SPEC_LABEL) == desired.fingerprint):
                    state = current.get("State", {})
                    from .runtime_profiles import EGRESS_REQUIRED, ROLE_LABEL
                    if (state.get("Running") is True and state.get("Health", {}).get("Status") == "healthy"
                        and metadata.get(EGRESS_REQUIRED) == "true"):
                        from .egress_runtime import companion_name
                        name = "/" + companion_name(desired.container_name)
                        for row in await self.engine.containers(desired.node_uuid):
                            if name in row.get("Names", []):
                                helper = await self.engine.inspect(row["Id"])
                                labels = helper.get("Config", {}).get("Labels", {}) if helper else {}
                                if (labels.get(DEPLOYMENT_LABEL)==str(desired.id) and labels.get(SPEC_LABEL)==desired.fingerprint
                                    and labels.get(ROLE_LABEL)=="egress"):
                                    return state_diagnostic(stage, helper.get("State"), component="egress", timeout=timeout)
                        return {"stage":stage,"component":"egress","reason":"helper_unhealthy"}
                    return state_diagnostic(stage,state,timeout=timeout)
        except (EngineFailure, OSError, ValueError, KeyError, TypeError):
            pass
        return {"stage":stage,"component":"controller","reason":"readiness_timeout" if timeout else "unknown"}

    async def rollback(self, operation: UUID, previous: Deployment | None, desired: Deployment):
        receipt = self.journal.get(operation)
        # Delivery/preflight failures leave the old process untouched.
        if receipt["phase"] in {"queued", "pulling"} or previous is None:
            self.journal.phase(operation, "failed", error="UPDATE_FAILED")
            return
        self.journal.phase(operation, "rolling_back", error="UPDATE_FAILED")
        try:
            current = [item for item in await self.observed() if item.deployment_uuid == desired.id]
            if len(current) > 1:
                raise EngineFailure("Ambiguous rollback target")
            if current and current[0].fingerprint != previous.fingerprint:
                await self.engine.remove_target(desired, current[0].container_id)
                current = []
            # stage() verifies/reuses an exact running prior instance and
            # repairs its companion if replacement stopped only part of it.
            container = await self.engine.stage(previous)
            await self.wait_ready(container)
            self.journal.restore(previous, container)
            # The requested update failed even if restoration succeeded.
            self.journal.phase(operation, "failed", container=container, error="UPDATE_FAILED")
        except (EngineFailure, TimeoutError):
            self.journal.phase(operation, "failed", error="ROLLBACK_FAILED")
