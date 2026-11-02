"""Cryptographic effect evidence and atomic Access-owner journal persistence."""

import base64
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy.dialects.postgresql import insert

from authorization._platform_persistence import OutboxRow, SecurityAuditRow
from authorization.application._reference_bindings import _KeyBinding
from authorization.domain.call_journal import CallEvidence, CallJournalEntry
from authorization.domain.owner_events import EventCall
from authorization.infrastructure.journal_records import AccessMutationEvent, McpCallAudit
from common.platform_db import PlatformDatabase
from node_protocol.effect import EffectPermit, NodeEffectPermit, SignedEffectPermit
from node_protocol.json_boundary import decode_json
from service_runtime.platform_db_mechanics import _DatabaseBinding


def call_evidence(permit: EffectPermit) -> CallEvidence:
    return CallEvidence(
        permit.request_uuid,
        permit.actor_uuid,
        permit.project_uuid,
        permit.agent_session_uuid if isinstance(permit, NodeEffectPermit) else None,
        permit.node_uuid,
        permit.placement_uuid,
        permit.module,
        permit.method,
        permit.tool,
        permit.issued_at,
        permit.expires_at,
    )


def verified_call(encoded: str, key: Ed25519PublicKey) -> EffectPermit:
    envelope = decode_json(base64.b64decode(encoded, validate=True), SignedEffectPermit)
    permit = envelope.permit
    key.verify(base64.b64decode(envelope.signature, validate=True), permit.signing_bytes())
    call_evidence(permit).require_recent_call(time.time())
    return permit


class SignedCallEvidence(_KeyBinding[Ed25519PublicKey]):
    def verify(self, encoded: str) -> CallEvidence:
        return call_evidence(verified_call(encoded, self.key))


class SqlCallJournal(_DatabaseBinding[PlatformDatabase]):
    async def record_once(self, entry: CallJournalEntry) -> None:
        evidence = entry.evidence
        if not evidence.tool:
            raise ValueError("Recent actual tool call required")
        metadata = EventCall(
            evidence.module,
            evidence.tool,
            entry.status,
            evidence.agent_session_uuid,
            evidence.node_uuid,
            evidence.placement_uuid,
            entry.duration_ms,
            "gateway-mcp",
        )
        async with self.database.transaction() as tx:
            created = await tx.execute(
                insert(SecurityAuditRow)
                .values(
                    id=evidence.request_uuid,
                    actor_id=evidence.actor_uuid,
                    project_id=evidence.project_uuid,
                    action=entry.event_name,
                    object_id=str(evidence.entity_uuid),
                    details=McpCallAudit(operation_uuid=evidence.request_uuid, call=metadata),
                )
                .on_conflict_do_nothing(index_elements=[SecurityAuditRow.id])
                .returning(SecurityAuditRow.id)
            )
            if created.scalar_one_or_none() is not None:
                tx.add(
                    OutboxRow(
                        id=evidence.request_uuid,
                        event_name=entry.event_name,
                        event_payload=AccessMutationEvent(
                            operation_uuid=evidence.request_uuid,
                            project_id=evidence.project_uuid,
                            entity_id=evidence.entity_uuid,
                        ),
                    )
                )
