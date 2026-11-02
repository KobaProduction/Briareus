"""Compose the one-time first-operator use case without a public route."""

from datetime import UTC, datetime

from common.platform_db import PlatformDatabase
from projects._rauthy_user_status import _LOCAL_SANDBOX_ISSUER, _PUBLIC_ISSUER
from projects.application.bootstrap import BootstrapFirstOperator
from projects.application.bootstrap import (
    TrustedFirstOperatorAuthority as TrustedFirstOperatorAuthority,
)
from projects.application.user_links import TrustedRauthyUserStatusPort
from projects.domain.bootstrap import FirstOperatorBootstrapDenied as FirstOperatorBootstrapDenied
from projects.domain.bootstrap import (
    FirstOperatorBootstrapUnavailable as FirstOperatorBootstrapUnavailable,
)
from projects.domain.bootstrap import VerifiedFirstOperatorApproval as VerifiedFirstOperatorApproval
from projects.domain.membership import CurrentRauthyUserLink
from projects.infrastructure.bootstrap import SqlBootstrapUnitOfWork


class FirstOperatorBootstrap:
    def __init__(
        self,
        *,
        database: PlatformDatabase,
        authority: TrustedFirstOperatorAuthority | None,
        rauthy_status: TrustedRauthyUserStatusPort | None,
    ) -> None:
        if (
            database.engine.url.database != "briareus_platform"
            or authority is None
            or rauthy_status is None
        ):
            raise ValueError("first operator bootstrap requires trusted own-DB and provider ports")
        self._use_case = BootstrapFirstOperator(
            authority,
            rauthy_status,
            SqlBootstrapUnitOfWork(database),
            frozenset({_PUBLIC_ISSUER, _LOCAL_SANDBOX_ISSUER}),
            lambda: datetime.now(UTC),
        )

    async def enroll_once(self, *, signed_evidence: object) -> CurrentRauthyUserLink:
        return await self._use_case.execute(signed_evidence)
