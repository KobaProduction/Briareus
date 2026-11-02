"""Adapt the existing account verifier's typed provider result to an affirmative fact."""

from application._accounts_binding import _AccountsBinding
from application.services import AccountService
from application.web_accounts import CandidateVerification
from domain.accounts import Account


class LegacyCandidateVerifier(_AccountsBinding[AccountService]):
    async def verify(
        self,
        account: Account,
        *,
        credential: str,
        credential_account_id: str,
    ) -> CandidateVerification:
        result = await self._accounts.verify_candidate(
            account,
            credential=credential,
            credential_account_id=credential_account_id,
        )
        return CandidateVerification(result.ok is True)
