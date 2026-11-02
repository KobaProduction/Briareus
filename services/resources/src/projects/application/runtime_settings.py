"""Save/read execution policy without restarting workers or granting authority."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from projects.application._transaction_binding import _TransactionClockBinding
from projects.domain.runtime_settings import (
    RuntimeNodeMissing,
    RuntimeOverrides,
    RuntimePolicyConflict,
    RuntimePolicyForbidden,
    RuntimePolicyIdentity,
    RuntimePolicyView,
    RuntimeScope,
    StoredRuntimePolicy,
    resolve_runtime,
)


@dataclass(frozen=True)
class RuntimePolicyReceipt:
    fingerprint: str
    actor_scope: str
    project_scope: str
    encrypted_outcome: str | None

    def require_matches(self, identity: RuntimePolicyIdentity) -> None:
        if (
            self.fingerprint != identity.fingerprint
            or self.actor_scope != str(identity.actor_uuid)
            or self.project_scope != str(identity.project_uuid)
        ):
            raise RuntimePolicyConflict("Operation identity conflict")


class RuntimeSettingsSession(Protocol):
    async def lock(self, key: str) -> StoredRuntimePolicy | None: ...
    async def node_exists(self, node_uuid: UUID) -> bool: ...
    async def get(self, key: str) -> StoredRuntimePolicy | None: ...
    async def receipt(self, operation_uuid: UUID) -> RuntimePolicyReceipt | None: ...
    def replay(self, receipt: RuntimePolicyReceipt) -> RuntimePolicyView: ...
    async def save(self, key: str, policy: StoredRuntimePolicy) -> None: ...
    async def complete(
        self, identity: RuntimePolicyIdentity, key: str, view: RuntimePolicyView, now: datetime
    ) -> None: ...


class RuntimeSettingsTransactions(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[RuntimeSettingsSession]: ...


class ManageRuntimeSettings(_TransactionClockBinding[RuntimeSettingsTransactions]):
    async def execute(
        self,
        identity: RuntimePolicyIdentity,
        *,
        scope: RuntimeScope,
        node_uuid: UUID | None,
        overrides: RuntimeOverrides | None,
        expiry: datetime,
    ) -> RuntimePolicyView:
        key = "node:" + str(node_uuid) if node_uuid is not None else "server"
        async with self._transactions.transaction() as session:
            row = await session.lock(key)
            if node_uuid is not None and not await session.node_exists(node_uuid):
                raise RuntimeNodeMissing("Node not found")
            if overrides is not None:
                receipt = await session.receipt(identity.operation_uuid)
                if receipt is not None:
                    receipt.require_matches(identity)
                    replay = session.replay(receipt)
                    require_current(expiry, self._now())
                    return replay
                row = next_policy(identity, row, overrides)
                await session.save(key, row)
            server = await session.get("server")
            node = await session.get("node:" + str(node_uuid)) if node_uuid is not None else None
            effective = resolve_runtime(
                server.overrides if server else RuntimeOverrides(),
                node.overrides if node else RuntimeOverrides(),
            )
            view = RuntimePolicyView(
                scope,
                node_uuid,
                row.sequence if row else 0,
                row.overrides if row else RuntimeOverrides(),
                effective,
            )
            require_current(expiry, self._now())
            if overrides is not None:
                await session.complete(identity, key, view, self._now())
        return view


def next_policy(
    identity: RuntimePolicyIdentity,
    previous: StoredRuntimePolicy | None,
    overrides: RuntimeOverrides,
) -> StoredRuntimePolicy:
    current = previous.sequence if previous else 0
    if identity.expected_sequence != current:
        raise RuntimePolicyConflict("Runtime settings changed")
    return StoredRuntimePolicy(current + 1, overrides)


def require_current(expiry: datetime, now: datetime) -> None:
    if expiry <= now:
        raise RuntimePolicyForbidden("Platform proof expired")
