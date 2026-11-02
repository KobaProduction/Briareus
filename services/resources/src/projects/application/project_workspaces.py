"""Workspace creation/replay shares a transaction and the placement node lock."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from projects.application._transaction_binding import _TransactionClockBinding
from projects.domain.project_workspaces import (
    ProjectWorkspace,
    WorkspaceActor,
    WorkspaceIdentity,
    WorkspaceNode,
    WorkspaceRejected,
    WorkspaceReplay,
)


@dataclass(frozen=True)
class WorkspaceReceipt:
    actor_scope: str
    project_scope: str
    fingerprint: str
    state: str
    encrypted_outcome: str | None

    def require_matches(self, identity: WorkspaceIdentity) -> None:
        if (
            self.fingerprint != identity.fingerprint
            or self.actor_scope != str(identity.actor_uuid)
            or self.project_scope != str(identity.project_uuid)
            or self.state != "completed"
        ):
            raise WorkspaceRejected("Workspace operation identity conflicts")


class WorkspaceSession(Protocol):
    async def lock_node(self, identity: WorkspaceIdentity) -> WorkspaceNode | None: ...
    async def workspace(self, identity: WorkspaceIdentity) -> ProjectWorkspace | None: ...
    async def receipt(self, identity: WorkspaceIdentity) -> WorkspaceReceipt | None: ...
    def replay(self, receipt: WorkspaceReceipt) -> WorkspaceReplay: ...
    async def create(self, identity: WorkspaceIdentity) -> ProjectWorkspace: ...
    async def complete(
        self, identity: WorkspaceIdentity, workspace: ProjectWorkspace, now: datetime
    ) -> None: ...


class WorkspaceTransactions(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[WorkspaceSession]: ...


@dataclass(frozen=True)
class WorkspaceResult:
    ensured: bool
    workspace: ProjectWorkspace | None


class ProjectWorkspaces(_TransactionClockBinding[WorkspaceTransactions]):
    async def execute(
        self, identity: WorkspaceIdentity, actor: WorkspaceActor, *, ensure: bool, expiry: datetime
    ) -> WorkspaceResult:
        async with self._transactions.transaction() as session:
            node = await session.lock_node(identity)
            if node is None:
                raise WorkspaceRejected("An enabled paired node is required")
            node.require_usable(actor)
            workspace = await session.workspace(identity)
            if workspace is not None:
                workspace.require_persistent()
            if ensure:
                workspace = await ensure_workspace(session, identity, workspace, self._now)
            if expiry <= self._now():
                raise WorkspaceRejected("Current Platform proof required", forbidden=True)
        return WorkspaceResult(ensure, workspace)


async def ensure_workspace(
    session: WorkspaceSession,
    identity: WorkspaceIdentity,
    current: ProjectWorkspace | None,
    now: Callable[[], datetime],
) -> ProjectWorkspace:
    receipt = await session.receipt(identity)
    if receipt is not None:
        receipt.require_matches(identity)
        replay = session.replay(receipt)
        replay.require_current(identity, current)
        return replay.workspace
    workspace = current if current is not None else await session.create(identity)
    await session.complete(identity, workspace, now())
    return workspace
