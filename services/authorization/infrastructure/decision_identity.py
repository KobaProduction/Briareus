"""Provider signature verification adapter for decision identity use cases."""

from authorization.domain.rauthy import VerifiedRauthySubject
from authorization.infrastructure.issuer_keys import TrustedRauthyIssuerKeys
from authorization.infrastructure.rauthy_tokens import RauthyJwksVerifier
from service_runtime._reference_bindings import _VerifierBinding


class RauthyDecisionBearer(_VerifierBinding[RauthyJwksVerifier | TrustedRauthyIssuerKeys]):
    async def verify(self, bearer: str) -> VerifiedRauthySubject:
        verifier = (
            await self._verifier.get_verifier()
            if isinstance(self._verifier, TrustedRauthyIssuerKeys)
            else self._verifier
        )
        return verifier.verify_access_token(bearer)
