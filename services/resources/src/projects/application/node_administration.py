"""Current operator admission and transactional node registration/configuration."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol
from uuid import UUID

from projects.application._transaction_binding import (
    _PlatformClockBinding,
    _TransactionClockBinding,
)
from projects.domain.node_administration import (
    ChangeNode,
    ManagedNode,
    NewNode,
    NodeActor,
    NodeCommandIdentity,
    NodeConflict,
    NodeForbidden,
    NodeInvalid,
    NodeMissing,
    NodeReceiptUnavailable,
    NodeSourceUnavailable,
    OperatorAuthority,
    OperatorEvidence,
    OperatorSelector,
    attest_operator,
    node_name,
)


@dataclass(frozen=True)
class ActorLookup:
    status: int
    evidence: OperatorEvidence | None


class PlatformActors(Protocol):
    async def read(self, selector: OperatorSelector) -> ActorLookup: ...


class AuthorizeNodeOperator(_PlatformClockBinding[PlatformActors]):
    async def execute(self, selector: OperatorSelector) -> OperatorAuthority:
        selector.require_current(self._now())
        found = await self._platform.read(selector)
        if found.status != 200:
            if found.status == 403:
                raise NodeForbidden("Current Platform source required")
            raise NodeSourceUnavailable("Current Platform source required")
        if found.evidence is None:
            raise NodeForbidden("Current Platform operator required")
        result = attest_operator(selector, found.evidence, self._now())
        selector.require_current(self._now())
        return result


@dataclass(frozen=True)
class NodeReceipt:
    fingerprint: str
    actor_scope: str
    project_scope: str
    state: str
    encrypted_outcome: str | None

    def require_matches(self, identity: NodeCommandIdentity) -> None:
        if (
            self.fingerprint != identity.fingerprint
            or self.actor_scope != str(identity.actor_uuid)
            or self.project_scope != str(identity.project_uuid)
            or self.state != "completed"
        ):
            raise NodeConflict("Operation identity conflict")


@dataclass(frozen=True)
class NodeReplay:
    operation: str
    digest: str
    node: ManagedNode

    def require_matches(self, identity: NodeCommandIdentity) -> None:
        if self.digest != identity.fingerprint or self.operation != str(identity.operation_uuid):
            raise NodeReceiptUnavailable("Operation receipt unavailable")


class NodeAdministrationSession(Protocol):
    async def nodes(self) -> tuple[ManagedNode, ...]: ...
    async def receipt(self, identity: NodeCommandIdentity) -> NodeReceipt | None: ...
    def replay(self, receipt: NodeReceipt) -> NodeReplay: ...
    async def registered(self, node_uuid: UUID) -> bool: ...
    async def register(self, node: NewNode, now: datetime) -> ManagedNode: ...
    async def node(self, node_uuid: UUID) -> ManagedNode | None: ...
    async def save(self, node: ManagedNode) -> None: ...
    async def complete(
        self, identity: NodeCommandIdentity, node: ManagedNode, now: datetime
    ) -> None: ...


class NodeAdministrationTransactions(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[NodeAdministrationSession]: ...


@dataclass(frozen=True)
class NodeInventory:
    items: tuple[ManagedNode, ...]
    truncated: bool


class ReadNodes(_TransactionClockBinding[NodeAdministrationTransactions]):
    async def execute(self, expiry: datetime) -> NodeInventory:
        async with self._transactions.transaction() as session:
            nodes = await session.nodes()
            require_current(expiry, self._now())
        return NodeInventory(nodes[:100], len(nodes) > 100)


class ConfigureNode(_TransactionClockBinding[NodeAdministrationTransactions]):
    async def execute(
        self,
        identity: NodeCommandIdentity,
        command: NewNode | ChangeNode,
        actor: NodeActor,
        expiry: datetime,
    ) -> ManagedNode:
        if actor.actor_uuid != identity.actor_uuid:
            raise NodeForbidden("Current Platform operator required")
        async with self._transactions.transaction() as session:
            receipt = await session.receipt(identity)
            if receipt is not None:
                receipt.require_matches(identity)
                replay = session.replay(receipt)
                replay.require_matches(identity)
                require_current(expiry, self._now())
                return replay.node
            if isinstance(command, NewNode):
                command.require_owner(actor)
                if await session.registered(command.id):
                    raise NodeConflict("Node already registered")
                node = await session.register(command, self._now())
            else:
                node = await change_node(session, command)
            require_current(expiry, self._now())
            await session.complete(identity, node, self._now())
        return node


async def change_node(session: NodeAdministrationSession, command: ChangeNode) -> ManagedNode:
    node = await session.node(command.node_uuid)
    if node is None:
        raise NodeMissing("Node not found")
    if node.sequence != command.sequence:
        raise NodeConflict("Node configuration changed")
    if command.action == "rename":
        updated = replace(node, name=node_name(command.name), sequence=node.sequence + 1)
    else:
        if command.name:
            raise NodeInvalid("Disable does not rename a node")
        updated = replace(node, enabled=False, sequence=node.sequence + 1)
    await session.save(updated)
    return updated


def require_current(expiry: datetime, now: datetime) -> None:
    if expiry <= now:
        raise NodeForbidden("Platform proof expired")
