"""Read and lock only the originating owner's exact durable command row."""

from __future__ import annotations

from importlib import import_module

from sqlalchemy import Table, select

from common.domain.owner_authority import OwnerAuthorityUnavailable
from common.domain.owner_bff import BffOwner, OriginalBffSelector, StoredOriginalOwnerState
from common.platform_db import PlatformDatabase

SOURCE_DATABASES: dict[BffOwner, str] = {
    "identity": "briareus_identity",
    "access": "briareus_access",
    "control": "briareus_platform",
    "catalog": "briareus_resources",
}
_SOURCE_LEDGER: dict[BffOwner, tuple[str, str]] = {
    "identity": ("identity._owner_ledger", "OwnerCommandRow"),
    "access": ("authorization._platform_persistence", "IdempotencyRow"),
    "control": ("projects._control_ledger", "OwnerCommandRow"),
    "catalog": ("projects._catalog_ledger", "OwnerCommandRow"),
}


class SqlOriginalOwnerLedger:
    def __init__(self, owner: BffOwner, database: PlatformDatabase) -> None:
        if database.engine.url.database != SOURCE_DATABASES[owner]:
            raise RuntimeError("BFF signer must use the originating owner SQL and live C2")
        self.owner, self.database = owner, database
        module, name = _SOURCE_LEDGER[owner]
        table = getattr(import_module(module), name).__table__
        if not isinstance(table, Table):
            raise RuntimeError("Original owner ledger table required")
        self.table = table

    async def inspect(
        self, selector: OriginalBffSelector, project_scope: str
    ) -> StoredOriginalOwnerState:
        if selector.owner != self.owner:
            raise OwnerAuthorityUnavailable("original owner command not durably found")
        table = self.table
        clauses = [
            table.c.actor_scope == str(selector.actor_user_id),
            table.c.project_scope == project_scope,
            table.c.operation == selector.original_operation,
            table.c.key == selector.original_key,
        ]
        if self.owner == "access":
            status, encrypted = table.c.status, table.c.response_ciphertext
        else:
            clauses.append(table.c.operation_uuid == selector.operation_uuid)
            status, encrypted = table.c.state, table.c.encrypted_outcome
        async with self.database.transaction() as transaction:
            record = (
                await transaction.execute(
                    select(status, encrypted).where(*clauses).with_for_update()
                )
            ).one_or_none()
            if record is None:
                raise OwnerAuthorityUnavailable("original owner command not durably found")
            state = record[0]
            if not isinstance(state, str):
                raise OwnerAuthorityUnavailable("original owner effect state is not verified")
            return StoredOriginalOwnerState(state, record[1] is not None)
