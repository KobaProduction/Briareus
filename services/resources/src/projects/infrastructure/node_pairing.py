"""Bounded operator-pinned bootstrap identity; this never marks a Node paired."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from common.platform_db import PlatformDatabase
from projects._journal_persistence import NodePairIntentRow
from projects._node_persistence import NodeRow
from projects.domain.execution_journal import JournalConflict, JournalRejected


async def remember_pair_intent(
    database: PlatformDatabase,
    *,
    node_uuid: UUID,
    operation_uuid: UUID,
    actor_uuid: UUID,
    project_uuid: UUID,
    expected_sequence: int,
    endpoint: str,
    pinned: str | None,
    public_key: str,
    fingerprint: str,
    expiry: datetime,
) -> None:
    async with database.transaction() as tx:
        node = await tx.scalar(select(NodeRow).where(NodeRow.id == node_uuid).with_for_update())
        if (
            node is None
            or node.deleted_at is not None
            or node.sequence != expected_sequence
            or node.endpoint != endpoint
            or node.public_key != pinned
        ):
            raise JournalConflict("Node configuration changed; reconcile enrollment")
        if expiry <= datetime.now(UTC):
            raise JournalRejected("Platform proof expired")
        if node.public_key is not None:
            return
        intent = await tx.get(NodePairIntentRow, operation_uuid)
        expected = (node_uuid, actor_uuid, project_uuid, expected_sequence, public_key, fingerprint)
        if intent is not None:
            actual = (
                intent.node_uuid,
                intent.actor_uuid,
                intent.project_uuid,
                intent.expected_sequence,
                intent.public_key,
                intent.fingerprint,
            )
            if actual != expected:
                raise JournalConflict("Node pairing operation identity conflicts")
            intent.expires_at = expiry
        else:
            tx.add(
                NodePairIntentRow(
                    operation_uuid=operation_uuid,
                    node_uuid=node_uuid,
                    actor_uuid=actor_uuid,
                    project_uuid=project_uuid,
                    expected_sequence=expected_sequence,
                    public_key=public_key,
                    fingerprint=fingerprint,
                    expires_at=expiry,
                )
            )
