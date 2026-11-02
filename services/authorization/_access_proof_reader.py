"""Access-owned current AgentSession proof composition; no other owner SQL."""

from pydantic import SecretStr

from authorization.application.access_proofs import IssueAccessOwnerProof
from authorization.domain.access_proofs import AccessProofQuery, AccessProofUnavailable
from authorization.domain.access_proofs import VerifiedAccessActor as VerifiedAccessActor
from authorization.infrastructure.access_proofs import (
    SourceAccessProofAuthorities,
    SourceAccessProofSigner,
    SqlAccessProofTransactions,
)
from authorization.infrastructure.access_proofs import (
    TrustedAccessActorSource as TrustedAccessActorSource,
)
from common.owner_contracts import (
    OwnerAuthorityUnavailable,
    OwnerCommandDTO,
    TrustedOwnerServicePeerPort,
)
from common.owner_proof_signing import SourceOwnerSigner
from common.platform_db import PlatformDatabase


class AccessOwnerProofReader:
    def __init__(
        self,
        database: PlatformDatabase,
        signer: SourceOwnerSigner,
        peers: TrustedOwnerServicePeerPort | None,
        actor_source: TrustedAccessActorSource | None,
    ) -> None:
        if (
            database.engine.url.database != "briareus_access"
            or peers is None
            or actor_source is None
        ):
            raise RuntimeError("Access source requires own database and trusted caller")
        self.db = database
        self.signer = signer
        self.peers = peers
        self.actors = actor_source

    async def issue_live_agent_session_grant(
        self,
        command: OwnerCommandDTO,
        *,
        peer_evidence: object,
        human_evidence: object,
    ) -> SecretStr:
        query = AccessProofQuery(
            command.operation,
            command.caller_user_id,
            command.project_id,
            command.session_uuid,
            command.expected_identity_revision,
            command.expected_access_revision,
        )
        use_case = IssueAccessOwnerProof(
            SourceAccessProofAuthorities(self.peers, self.actors),
            SqlAccessProofTransactions(self.db),
            SourceAccessProofSigner(self.signer, command),
        )
        try:
            return await use_case.execute(query, peer_evidence, human_evidence)
        except AccessProofUnavailable as exc:
            raise OwnerAuthorityUnavailable(str(exc)) from None
