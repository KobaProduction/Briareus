"""Access SQL, trusted source evidence and cryptographic owner-proof adapters."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._access_cedar import permits_current_project_grant
from authorization._session_persistence import ProjectAgentSessionRow
from authorization.domain.access_proofs import (
    AccessProofAuthority,
    AccessProofQuery,
    AccessProofSession,
    VerifiedAccessActor,
)
from common.owner_contracts import (
    OwnerCommandDTO,
    TrustedOwnerServicePeerPort,
    VerifiedOwnerServicePeer,
)
from common.owner_proof_signing import OwnerVerifiedSourceSnapshot, SourceOwnerSigner
from common.platform_db import PlatformDatabase
from service_runtime.platform_db_mechanics import _PrivateDatabaseBinding


class TrustedAccessActorSource(Protocol):
    def verify_actor(
        self, evidence: object, *, peer: VerifiedOwnerServicePeer
    ) -> VerifiedAccessActor: ...


class SourceAccessProofAuthorities:
    def __init__(
        self, peers: TrustedOwnerServicePeerPort, actors: TrustedAccessActorSource
    ) -> None:
        self._peers = peers
        self._actors = actors

    def verify(self, peer_evidence: object, human_evidence: object) -> AccessProofAuthority:
        peer = self._peers.verify_peer(peer_evidence)
        actor = self._actors.verify_actor(human_evidence, peer=peer)
        return AccessProofAuthority(actor, peer.service_id, peer.audience, peer.expires_at)


class SqlAccessProofTransaction:
    def __init__(self, transaction: AsyncSession) -> None:
        self._transaction = transaction
        self._row: ProjectAgentSessionRow | None = None

    async def session(self, query: AccessProofQuery) -> AccessProofSession | None:
        row = await self._transaction.scalar(
            select(ProjectAgentSessionRow)
            .where(ProjectAgentSessionRow.session_uuid == query.session_uuid)
            .with_for_update()
        )
        self._row = row
        if row is None:
            return None
        return AccessProofSession(
            row.session_uuid,
            row.project_id,
            row.created_by_principal_id,
            row.version,
            row.status,
            row.hard_expires_at,
            row.grants.operations,
        )

    def permits(self, query: AccessProofQuery, grant: str) -> bool:
        if self._row is None:
            return False
        return permits_current_project_grant(
            row=self._row,
            actor_uuid=query.caller_uuid,
            project_uuid=query.project_uuid,
            operation=grant,
            expected_version=query.access_revision,
        )


class SqlAccessProofTransactions(_PrivateDatabaseBinding[PlatformDatabase]):
    @asynccontextmanager
    async def open(self) -> AsyncIterator[SqlAccessProofTransaction]:
        async with self._database.transaction() as transaction:
            yield SqlAccessProofTransaction(transaction)


class SourceAccessProofSigner:
    def __init__(self, signer: SourceOwnerSigner, command: OwnerCommandDTO) -> None:
        self._signer = signer
        self._command = command

    def sign(self, session: AccessProofSession, grant: str) -> SecretStr:
        snapshot = OwnerVerifiedSourceSnapshot(
            owner="access",
            caller_user_id=self._command.caller_user_id,
            project_id=session.project_uuid,
            agent_session_uuid=session.session_uuid,
            owner_revision=session.version,
            active=True,
            role=None,
            capabilities=(self._command.operation,),
            control_resource_revision=None,
            project_lifecycle=None,
            team_id=self._command.expected_team_id,
            team_revision=None,
            team_resource_revision=None,
            epoch_components=(
                str(session.session_uuid),
                str(session.version),
                session.status,
                session.hard_expires_at.isoformat(),
                str(session.project_uuid),
                str(self._command.caller_user_id),
                grant,
            ),
        )
        return self._signer.sign_project(self._command, snapshot)
