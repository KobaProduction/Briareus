"""Enroll a pinned execution peer without holding SQL locks across remote effects."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from node_protocol import NodeBudget, NodeRecord
from node_protocol.domain.observations import NodeConfiguration, NodeInventory
from projects.application.node_control import NodeExecutionControl, NodeUnavailable
from projects.domain.node_administration import (
    ManagedNode,
    NodeConflict,
    OperatorAuthority,
)


@dataclass(frozen=True)
class EnrollmentRequest:
    operation_uuid: UUID
    actor_uuid: UUID
    project_uuid: UUID
    node_uuid: UUID
    expected_sequence: int
    action: Literal["setup", "pair", "enable", "budget"]
    fingerprint: str
    public_key: str
    budget: NodeBudget | None

    @property
    def operation(self) -> str:
        return "node." + self.action


@dataclass(frozen=True)
class EnrollmentTarget:
    record: NodeRecord
    endpoint: str
    pinned: str | None
    runtime_uid: int


@dataclass(frozen=True)
class EnrollmentAcknowledgement:
    public_key: str
    budget: NodeBudget | None


class EnrollmentStore(Protocol):
    async def read(self, request: EnrollmentRequest) -> ManagedNode | EnrollmentTarget: ...

    async def remember_pair(
        self,
        request: EnrollmentRequest,
        target: EnrollmentTarget,
        public_key: str,
        expiry: datetime,
    ) -> None: ...

    async def complete(
        self,
        request: EnrollmentRequest,
        target: EnrollmentTarget,
        acknowledgement: EnrollmentAcknowledgement,
        expiry: datetime,
    ) -> ManagedNode: ...


class EnrollNode:
    def __init__(
        self,
        store: EnrollmentStore,
        remote: NodeExecutionControl,
        authorize: Callable[[], Awaitable[OperatorAuthority]],
        canonical_key: Callable[[str], str],
    ) -> None:
        self._store, self._remote = store, remote
        self._authorize, self._canonical_key = authorize, canonical_key

    async def execute(self, request: EnrollmentRequest) -> ManagedNode | EnrollmentTarget:
        target = await self._store.read(request)
        if isinstance(target, ManagedNode):
            await self._authorize()
            return target
        if request.action == "setup":
            return target
        acknowledgement = (
            await self._pair(request, target)
            if request.action == "pair"
            else await self._configure(request, target)
        )
        authority = await self._authorize()
        return await self._store.complete(request, target, acknowledgement, authority.expires_at)

    async def _pair(
        self, request: EnrollmentRequest, target: EnrollmentTarget
    ) -> EnrollmentAcknowledgement:
        public_key = self._canonical_key(request.public_key)
        if target.pinned and target.pinned != public_key:
            raise NodeConflict("Node identity rotation requires separate recovery")
        authority = await self._authorize()
        await self._store.remember_pair(request, target, public_key, authority.expires_at)
        observation = await self._remote.call(
            endpoint=target.endpoint,
            public_key=public_key,
            node_uuid=target.record.id,
            operation_uuid=request.operation_uuid,
            sequence=request.expected_sequence,
        )
        if not isinstance(observation, NodeInventory) or observation.node_uuid != target.record.id:
            raise NodeUnavailable("Invalid node inventory")
        return EnrollmentAcknowledgement(public_key, None)

    async def _configure(
        self, request: EnrollmentRequest, target: EnrollmentTarget
    ) -> EnrollmentAcknowledgement:
        if not target.pinned:
            raise NodeConflict("Verified node identity required")
        candidate = (
            target.record.model_copy(update={"budget": request.budget})
            if request.action == "budget"
            else target.record.model_copy(update={"enabled": True})
        )
        observation = await self._remote.call(
            endpoint=target.endpoint,
            public_key=target.pinned,
            node_uuid=target.record.id,
            operation_uuid=request.operation_uuid,
            sequence=request.expected_sequence + 1,
            action="configure",
            record=candidate,
        )
        if (
            not isinstance(observation, NodeConfiguration)
            or observation.node_uuid != target.record.id
            or observation.enabled is not candidate.enabled
            or observation.sequence != request.expected_sequence + 1
        ):
            raise NodeUnavailable("Node configuration not acknowledged")
        return EnrollmentAcknowledgement(target.pinned, candidate.budget)
