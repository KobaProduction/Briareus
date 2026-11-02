"""Resolve a signed browser identity through current independent Platform authority."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from control_panel_api.domain.oidc_identity import OidcSessionStoreUnavailable
from control_panel_api.domain.platform_authority import PanelOidcSession, ResolvedPlatformUser
from control_panel_api.domain.platform_membership import (
    MembershipProofFailure,
    validate_membership_proof,
)


class PlatformMembershipUnavailable(Exception):
    """Trusted current owner membership could not be obtained."""


class CurrentPlatformUserSource(Protocol):
    async def resolve(self, *, issuer: str, subject: str) -> ResolvedPlatformUser | None: ...
    async def resolve_project(
        self, *, issuer: str, subject: str, project_uuid: UUID
    ) -> ResolvedPlatformUser | None: ...


class MembershipSessions(Protocol):
    async def get_session(self, ticket: str) -> PanelOidcSession | None: ...
    async def delete_session(self, ticket: str) -> None: ...


@dataclass(frozen=True, slots=True)
class MembershipContext:
    session: PanelOidcSession
    user: ResolvedPlatformUser


@dataclass(frozen=True, slots=True)
class MembershipFailure:
    status: int
    code: str
    clear_cookie: bool = False


class CurrentMembership:
    def __init__(
        self,
        sessions: MembershipSessions,
        source: CurrentPlatformUserSource | None,
        *,
        expected_issuer: str | None,
        expected_client_id: str | None,
    ) -> None:
        if (expected_issuer is None) != (expected_client_id is None):
            raise ValueError("OIDC membership realm must bind issuer and client together")
        if expected_issuer is not None and (
            not expected_issuer.startswith("https://") or not expected_client_id
        ):
            raise ValueError("invalid OIDC membership realm")
        self._sessions = sessions
        self._source = source
        self._issuer = expected_issuer
        self._client_id = expected_client_id

    async def _session(self, ticket: str) -> PanelOidcSession | MembershipFailure:
        try:
            session = await self._sessions.get_session(ticket)
        except OidcSessionStoreUnavailable:
            return MembershipFailure(503, "OIDC_SESSION_STORE_UNAVAILABLE")
        if session is None:
            return MembershipFailure(401, "OIDC_SESSION_EXPIRED")
        if self._issuer is None or (
            session.issuer.rstrip("/") == self._issuer.rstrip("/")
            and session.client_id == self._client_id
        ):
            return session
        try:
            await self._sessions.delete_session(ticket)
        except OidcSessionStoreUnavailable:
            return MembershipFailure(503, "OIDC_STALE_SESSION_REVOCATION_UNAVAILABLE")
        return MembershipFailure(401, "OIDC_SESSION_REALM_MISMATCH", clear_cookie=True)

    async def _proof(
        self, session: PanelOidcSession, project_uuid: UUID | None
    ) -> ResolvedPlatformUser | MembershipFailure:
        if self._source is None:
            return MembershipFailure(503, "PLATFORM_MEMBERSHIP_SOURCE_UNAVAILABLE")
        try:
            if project_uuid is None:
                proof = await self._source.resolve(issuer=session.issuer, subject=session.subject)
            else:
                if project_uuid.version != 4:
                    return MembershipFailure(403, "PROJECT_ACCESS_DENIED")
                proof = await self._source.resolve_project(
                    issuer=session.issuer, subject=session.subject, project_uuid=project_uuid
                )
        except Exception:
            # Unknown peer failures never open access or expose owner internals.
            return MembershipFailure(503, "PLATFORM_MEMBERSHIP_SOURCE_UNAVAILABLE")
        return (
            proof if proof is not None else MembershipFailure(403, "PLATFORM_MEMBERSHIP_REQUIRED")
        )

    async def resolve(
        self, ticket: str, project_uuid: UUID | None
    ) -> MembershipContext | MembershipFailure:
        session = await self._session(ticket)
        if isinstance(session, MembershipFailure):
            return session
        proof = await self._proof(session, project_uuid)
        if isinstance(proof, MembershipFailure):
            return proof
        failure = validate_membership_proof(session, proof, project_uuid, now=datetime.now(UTC))
        if failure is not None:
            status = 403 if failure == MembershipProofFailure.NOT_CURRENT else 503
            return MembershipFailure(status, failure.value)
        return MembershipContext(session, proof)
