# FastAPI Header descriptors are framework-executed defaults
"""Unmounted Identity-owned login and current JWT issue/verification boundary.

No Admin API, Authorization, Control or Gateway may connect directly to
Identity's PostgreSQL. Only a source-authenticated internal TLS/Unix peer,
verified browser origin and a release-pinned issuer may issue a User bearer.
No cookie/username-header fallback, fake token or password in event logs.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import SecretStr

from common.owner_runtime import OwnerIngressVerifier, create_owner_app
from common.platform_db import OwnerDatabaseSettings
from identity._private_current_user import (
    IdentityCurrentUserSource,
    build_unmounted_identity_current_router,
)
from identity._service import IdentityService
from identity.application.private_login import (
    IdentitySourceUnavailable as IdentitySourceUnavailable,
)
from identity.application.private_login import (
    IssuedIdentityBearer as IssuedIdentityBearer,
)
from identity.application.private_login import (
    PrivateIdentityLogin,
)
from identity.application.private_login import (
    TrustedIdentityLoginAdmissionPort as TrustedIdentityLoginAdmissionPort,
)
from identity.application.private_login import (
    TrustedIdentitySessionIssuer as TrustedIdentitySessionIssuer,
)
from identity.application.private_login import (
    VerifiedIdentityLoginAdmission as VerifiedIdentityLoginAdmission,
)
from identity.infrastructure.original_login import SqlOriginalLoginLedger
from identity.presentation.private_login import (
    PrivateIdentityLoginPayload as PrivateIdentityLoginPayload,
)
from identity.presentation.private_login import (
    PrivateIdentityLoginResult as PrivateIdentityLoginResult,
)
from identity.presentation.private_login import (
    build_private_login_router,
    private_http_error_code,
)

if TYPE_CHECKING:
    from identity._private_onboarding import (
        IdentityPrivateInvitationRegistration,
        RestrictedFirstAdminCodeDelivery,
        RestrictedFirstAdminOperatorListener,
    )


class IdentityPrivateLoginSource:
    """Ready-to-inject real Identity password admission, never a public route."""

    def __init__(
        self,
        *,
        identity: IdentityService,
        ingress: TrustedIdentityLoginAdmissionPort,
        tokens: TrustedIdentitySessionIssuer,
        pinned_issuer: str,
        pinned_audience: str,
        login_pepper: bytes,
    ) -> None:
        if not all((identity, ingress, tokens, pinned_issuer, pinned_audience)):
            raise ValueError("Identity private login requires genuine owner/C2/session issuer")
        if len(login_pepper) < 32:
            raise ValueError("independent private Identity login rate-limit key required")
        self.identity_login_pepper = login_pepper
        if identity.database.engine.url.database != "briareus_identity":
            raise ValueError("Identity login must own only the Identity logical DB")
        self.identity = identity
        self.ingress = ingress
        self.tokens = tokens
        self.issuer = pinned_issuer
        self.audience = pinned_audience

    async def _reserve_original_login(
        self,
        *,
        original_uuid: UUID,
        username: str,
        password: SecretStr,
        admission: VerifiedIdentityLoginAdmission,
    ) -> UUID:
        return await SqlOriginalLoginLedger(
            self.identity.database, self.identity_login_pepper
        )._reserve_original_login(
            original_uuid=original_uuid, username=username, password=password, admission=admission
        )

    async def _complete_original_login(self, receipt_id: UUID) -> None:
        await SqlOriginalLoginLedger(
            self.identity.database, self.identity_login_pepper
        )._complete_original_login(receipt_id)

    async def login(
        self,
        *,
        evidence: object,
        username: str,
        password: SecretStr,
        original_uuid: UUID,
    ) -> IssuedIdentityBearer:
        return await self._use_cases().login(
            evidence=evidence, username=username, password=password, original_uuid=original_uuid
        )

    async def logout(self, *, evidence: object, bearer: SecretStr) -> None:
        await self._use_cases().logout(evidence=evidence, bearer=bearer)

    def _use_cases(self) -> PrivateIdentityLogin:
        return PrivateIdentityLogin(
            self.identity,
            self.ingress,
            self.tokens,
            self,
            self.issuer,
            self.audience,
            self.identity_login_pepper,
        )


def build_unmounted_private_identity_login_router(
    login: IdentityPrivateLoginSource,
) -> APIRouter:
    """Private Identity service ONLY; retain the concrete reviewed composition guard."""
    if not isinstance(login, IdentityPrivateLoginSource):
        raise ValueError("unverified Identity issuer cannot mount even privately")
    return build_private_login_router(login)


def create_unmounted_identity_private_app(
    login: IdentityPrivateLoginSource,
    *,
    db_settings: OwnerDatabaseSettings,
    trusted_ingress: OwnerIngressVerifier,
    current_users: IdentityCurrentUserSource,
    registration: IdentityPrivateInvitationRegistration,
    operator_delivery: RestrictedFirstAdminCodeDelivery | None = None,
    operator_listener: socket.socket | None = None,
) -> FastAPI:
    """SOURCE-only private Identity composition; default published app unchanged.

    Own Identity PostgreSQL schema migrates/verifies before any route accepts
    an actual call. The same reviewed URL/role must back source login and
    owner Alembic. Identity login issuer connection is closed at shutdown.
    """
    from identity._private_onboarding import (
        build_unmounted_invitation_registration_router,
    )

    _require_private_sources(login, registration, db_settings, trusted_ingress, current_users)
    operator_supervisor = _operator_supervisor(login.identity, operator_delivery, operator_listener)
    app = create_owner_app("identity", settings=db_settings, trusted_ingress=trusted_ingress)
    _install_private_lifespan(app, login, operator_supervisor, operator_listener)
    app.include_router(build_unmounted_private_identity_login_router(login))
    app.include_router(build_unmounted_invitation_registration_router(registration))
    app.include_router(build_unmounted_identity_current_router(current_users))

    _install_private_error_handlers(app)
    return app


def _require_private_sources(
    login: object,
    registration: object,
    db_settings: OwnerDatabaseSettings,
    trusted_ingress: object,
    current_users: object,
) -> None:
    from identity._private_onboarding import IdentityPrivateInvitationRegistration
    from identity._private_user_session import IdentityPrivateUserSessionIssuer

    if (
        not isinstance(login, IdentityPrivateLoginSource)
        or not isinstance(registration, IdentityPrivateInvitationRegistration)
        or db_settings.owner != "identity"
        or trusted_ingress is None
        or not isinstance(current_users, IdentityCurrentUserSource)
        or login.identity.database.engine.url != db_settings.url
        or current_users.db.engine.url != db_settings.url
        or registration.identity.database.engine.url != db_settings.url
        or registration.identity is not login.identity
        or not isinstance(login.tokens, IdentityPrivateUserSessionIssuer)
        or not login.tokens.matches_accepted_identity_source(
            database=login.identity.database,
            public_key=current_users.key,
            issuer=login.issuer,
            audience=login.audience,
        )
        or current_users.issuer != login.issuer
        or current_users.audience != login.audience
    ):
        raise ValueError("Identity private login/owner migrations must share reviewed DB")


def _operator_supervisor(
    identity: IdentityService,
    delivery: object | None,
    listener: object | None,
) -> RestrictedFirstAdminOperatorListener | None:
    from identity._private_onboarding import (
        RestrictedFirstAdminCodeDelivery,
        RestrictedFirstAdminOperatorListener,
    )

    if (delivery is None) != (listener is None):
        raise ValueError("operator socket and approved kernel gate must be provided together")
    if delivery is None:
        return None
    if (
        not isinstance(delivery, RestrictedFirstAdminCodeDelivery)
        or delivery.identity is not identity
        or not isinstance(listener, socket.socket)
        or listener.family != socket.AddressFamily.__members__.get("AF_UNIX")
        or listener.type & socket.SOCK_STREAM != socket.SOCK_STREAM
        or listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) != 1
    ):
        raise ValueError("first admin operator listener must share the current Identity owner")
    return RestrictedFirstAdminOperatorListener(delivery)


def _install_private_lifespan(
    app: FastAPI,
    login: IdentityPrivateLoginSource,
    operator_supervisor: RestrictedFirstAdminOperatorListener | None,
    operator_listener: socket.socket | None,
) -> None:
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def private_lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            async with original_lifespan(application):
                # Only a real supervisor-owned listening socket can activate
                # first-admin code delivery. No public HTTP/ENV bootstrap path.
                if operator_supervisor is None or operator_listener is None:
                    yield
                else:
                    task = asyncio.create_task(operator_supervisor.deliver_once(operator_listener))
                    try:
                        yield
                    finally:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
        finally:
            await login.identity.database.close()

    app.router.lifespan_context = private_lifespan


def _install_private_error_handlers(app: FastAPI) -> None:
    from identity._private_onboarding import IdentityRegistrationOutcomeUnknown

    @app.exception_handler(IdentityRegistrationOutcomeUnknown)
    async def registration_uncertain(
        _request: Request, _error: IdentityRegistrationOutcomeUnknown
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "OWNER_SOURCE_UNAVAILABLE",
                    "originalOutcomeUnknown": True,
                }
            },
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @app.exception_handler(HTTPException)
    async def private_http_failure(_request: Request, error: HTTPException) -> JSONResponse:
        # Never echo exception.detail or submitted User credentials. Only
        # allowed private BFF envelope codes cross the trusted Gateway.
        code = private_http_error_code(error.status_code)
        status = error.status_code if error.status_code in {401, 403, 422, 429} else 503
        return JSONResponse(
            status_code=status,
            content={"error": {"code": code, "originalOutcomeUnknown": False}},
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @app.exception_handler(RequestValidationError)
    async def private_input_rejected(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        # Never echo the submitted password/SecretStr or invalid token in a
        # Pydantic 422 validation body, even over the private ingress.
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "INVALID_INPUT", "originalOutcomeUnknown": False}},
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
