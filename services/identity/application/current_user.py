"""Current legacy user admission from verified peer, bearer and owner facts."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import SecretStr

from common.owner_bff_models import VerifiedAdminCaller
from common.private_user_token import IdentityCredentialRejected
from identity.domain.current_user import CurrentUserSnapshot


@dataclass(frozen=True)
class CurrentIdentityToken:
    subject_id: UUID
    jti: UUID
    credential_version: int


class CurrentUserPeer(Protocol):
    def require(self, evidence: object) -> None: ...


class CurrentUserBearer(Protocol):
    def require(self, bearer: SecretStr) -> CurrentIdentityToken: ...


class CurrentUserTransaction(Protocol):
    async def user(self, subject_id: UUID) -> CurrentUserSnapshot | None: ...

    async def revoked(self, jti: UUID) -> bool: ...


class CurrentUserTransactions(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[CurrentUserTransaction]: ...


@dataclass(frozen=True)
class RequireLegacyCurrentUser:
    peers: CurrentUserPeer
    bearers: CurrentUserBearer
    transactions: CurrentUserTransactions

    async def execute(self, bearer: SecretStr, peer_evidence: object) -> VerifiedAdminCaller:
        self.peers.require(peer_evidence)
        token = self.bearers.require(bearer)
        async with self.transactions() as tx:
            user = await tx.user(token.subject_id)
            if user is None or not user.current(token.credential_version):
                raise IdentityCredentialRejected("Identity user no longer active")
            if await tx.revoked(token.jti):
                raise IdentityCredentialRejected("Identity bearer JTI revoked")
            return VerifiedAdminCaller(
                user_id=token.subject_id,
                credential_version=user.credential_version,
                source="verified-admin-bearer",
            )
