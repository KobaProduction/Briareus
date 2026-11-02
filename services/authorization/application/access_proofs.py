"""Issue an owner proof only while the locked current grant remains valid."""

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Protocol

from pydantic import SecretStr

from authorization.domain.access_proofs import (
    AccessProofAuthority,
    AccessProofQuery,
    AccessProofSession,
    AccessProofUnavailable,
)


class AccessProofAuthorities(Protocol):
    def verify(self, peer_evidence: object, human_evidence: object) -> AccessProofAuthority: ...


class AccessProofTransaction(Protocol):
    async def session(self, query: AccessProofQuery) -> AccessProofSession | None: ...

    def permits(self, query: AccessProofQuery, grant: str) -> bool: ...


class AccessProofTransactions(Protocol):
    def open(self) -> AbstractAsyncContextManager[AccessProofTransaction]: ...


class AccessProofSigner(Protocol):
    def sign(self, session: AccessProofSession, grant: str) -> SecretStr: ...


class IssueAccessOwnerProof:
    def __init__(
        self,
        authorities: AccessProofAuthorities,
        transactions: AccessProofTransactions,
        signer: AccessProofSigner,
    ) -> None:
        self._authorities = authorities
        self._transactions = transactions
        self._signer = signer

    async def execute(
        self,
        query: AccessProofQuery,
        peer_evidence: object,
        human_evidence: object,
    ) -> SecretStr:
        needed = query.needed_grant()
        try:
            authority = self._authorities.verify(peer_evidence, human_evidence)
        except Exception:
            raise AccessProofUnavailable("Access trusted human/peer not verified") from None
        authority.require_current(query, datetime.now(UTC))
        async with self._transactions.open() as transaction:
            session = await transaction.session(query)
            if session is None:
                raise AccessProofUnavailable("Access session revoked, expired or wrong Project")
            session.require_current(query, needed, datetime.now(UTC))
            if not transaction.permits(query, needed):
                raise AccessProofUnavailable("Cedar denies current Project AgentSession grant")
            authority.require_current(query, datetime.now(UTC))
            session.require_current(query, needed, datetime.now(UTC))
            return self._signer.sign(session, needed)
