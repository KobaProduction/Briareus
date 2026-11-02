"""Private human runtime routing over independent authority and owner capabilities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from authorization.application.access_inputs import (
    ApprovalListCommand,
    OpenSessionCommand,
    RequestElevationCommand,
    ResolveElevationCommand,
    RevokeSessionCommand,
    SessionGetCommand,
)
from authorization.application.event_receipts import EventPageResponse as RuntimeEvents
from authorization.application.runtime_effects import RuntimePermit as RuntimePermit
from authorization.application.runtime_inputs import RuntimeAction as RuntimeAction
from authorization.application.runtime_inputs import (
    RuntimeCommand,
    RuntimeEffectCall,
    RuntimeEventQuery,
    RuntimeResourceQuery,
    RuntimeWriteCommand,
)
from authorization.application.session_receipts import (
    ElevationResponse,
    OpenSessionResponse,
    RevokeSessionResponse,
)
from authorization.domain.runtime_policy import RuntimeActor, RuntimeIdentity, bind_runtime_actor
from authorization.domain.session_reads import ApprovalReadEntry, SessionReadEntry
from runtime_peer.runtime_resource_receipts import RuntimeResources


@dataclass(frozen=True, slots=True)
class RuntimeRequest:
    identity: RuntimeIdentity
    action: RuntimeAction
    command: RuntimeCommand

    def command_as[T](self, expected: type[T]) -> T:
        if isinstance(self.command, expected):
            return self.command
        raise ValueError("Runtime command does not match action")

    def write_command(self) -> RuntimeWriteCommand:
        if isinstance(
            self.command,
            (
                OpenSessionCommand,
                RequestElevationCommand,
                ResolveElevationCommand,
                RevokeSessionCommand,
            ),
        ):
            return self.command
        raise ValueError("Runtime write command required")


@dataclass(frozen=True, slots=True)
class RuntimeSessions:
    items: tuple[SessionReadEntry, ...]
    detail: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeApprovals:
    items: tuple[ApprovalReadEntry, ...]


class RuntimeActorPort(Protocol):
    async def resolve(self, identity: RuntimeIdentity) -> RuntimeActor: ...


class RuntimeReadPort(Protocol):
    async def sessions(
        self, actor: RuntimeActor, command: ApprovalListCommand, *, detail: bool
    ) -> RuntimeSessions: ...
    async def approvals(
        self, actor: RuntimeActor, command: ApprovalListCommand
    ) -> RuntimeApprovals: ...
    async def events(self, actor: RuntimeActor, command: RuntimeEventQuery) -> RuntimeEvents: ...


class RuntimeResourcesPort(Protocol):
    async def catalogue(
        self, actor: RuntimeActor, command: RuntimeResourceQuery
    ) -> RuntimeResources: ...
    async def prepare(
        self, actor: RuntimeActor, hand: str, command: RuntimeEffectCall
    ) -> RuntimePermit: ...


@dataclass(frozen=True, slots=True)
class RuntimeWriteReceipt:
    status: int
    body: OpenSessionResponse | ElevationResponse | RevokeSessionResponse


class RuntimeWritePort(Protocol):
    async def execute(
        self,
        actor: RuntimeActor,
        action: RuntimeAction,
        command: RuntimeWriteCommand,
    ) -> RuntimeWriteReceipt: ...


RuntimeResult = (
    RuntimeSessions
    | RuntimeApprovals
    | RuntimeEvents
    | RuntimeResources
    | RuntimePermit
    | RuntimeWriteReceipt
)


class DispatchRuntime:
    def __init__(
        self,
        actors: RuntimeActorPort,
        reads: RuntimeReadPort,
        resources: RuntimeResourcesPort,
        writes: RuntimeWritePort,
        now: Callable[[], datetime],
    ) -> None:
        self._actors = actors
        self._reads = reads
        self._resources = resources
        self._writes = writes
        self._now = now

    async def execute(self, request: RuntimeRequest) -> RuntimeResult:
        began = self._now()
        request.identity.require_current(began)
        resolved = await self._actors.resolve(request.identity)
        actor = bind_runtime_actor(request.identity, resolved, began=began, now=self._now())
        action = request.action
        if action == "events.read":
            return await self._reads.events(actor, request.command_as(RuntimeEventQuery))
        if action in {"resource.list", "terminal.prepare", "files.prepare", "web.prepare"}:
            actor.require_resources()
            if action == "resource.list":
                return await self._resources.catalogue(
                    actor, request.command_as(RuntimeResourceQuery)
                )
            return await self._resources.prepare(
                actor, action.split(".")[0], request.command_as(RuntimeEffectCall)
            )
        if action in {"session.list", "session.get"}:
            return await self._reads.sessions(
                actor,
                request.command_as(SessionGetCommand)
                if action == "session.get"
                else request.command_as(ApprovalListCommand),
                detail=action == "session.get",
            )
        if action == "approval.list":
            return await self._reads.approvals(actor, request.command_as(ApprovalListCommand))
        return await self._writes.execute(actor, action, request.write_command())
