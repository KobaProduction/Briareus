"""Attested HTTP channel and bounded Platform projection response decoding."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from control_panel_api.application.platform_projection_client import PlatformProjectionChannel
from control_panel_api.domain.platform_authority import (
    PlatformProjectContext,
    PlatformTeamContext,
    ResolvedPlatformUser,
)
from control_panel_api.domain.platform_projection_client import (
    PlatformProjectionAuthority,
    PlatformProjectionInvalid,
    PlatformProjectionQuery,
)

from ._constructor_bindings import _PeerBinding

_OWNER_URL = "http://briareus-platform:8000/internal/v1/platform/oidc/current"


@dataclass(frozen=True, slots=True)
class VerifiedPlatformServiceTransport:
    client: httpx.AsyncClient
    mode: Literal["mtls", "unix-peer"]
    server_audience: Literal["briareus:platform"]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class VerifiedPanelDelegation:
    bearer: SecretStr
    subject: str
    issuer: str
    recipient: Literal["briareus:platform"]
    expires_at: datetime
    project_uuid: UUID | None = None


class TrustedPlatformPeerPort(Protocol):
    async def current_transport(self) -> VerifiedPlatformServiceTransport: ...
    async def signed_subject_delegation(
        self, *, issuer: str, subject: str
    ) -> VerifiedPanelDelegation: ...
    async def signed_project_delegation(
        self, *, issuer: str, subject: str, project_uuid: UUID
    ) -> VerifiedPanelDelegation: ...


def _checked_transport(raw: object) -> VerifiedPlatformServiceTransport:
    if not isinstance(raw, VerifiedPlatformServiceTransport):
        raise PlatformProjectionInvalid("untrusted Platform peer delegation")
    expiry: object = raw.expires_at
    if not isinstance(expiry, datetime):
        raise PlatformProjectionInvalid("untrusted Platform peer delegation")
    return raw


def _checked_delegation(raw: object) -> VerifiedPanelDelegation:
    if not isinstance(raw, VerifiedPanelDelegation):
        raise PlatformProjectionInvalid("untrusted Platform peer delegation")
    expiry: object = raw.expires_at
    if not isinstance(expiry, datetime):
        raise PlatformProjectionInvalid("untrusted Platform peer delegation")
    return raw


class _Team(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    team_uuid: UUID
    owner: bool
    name: str | None = Field(default=None, max_length=255)
    member: bool = True


class _Project(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_uuid: UUID
    name: str | None = Field(default=None, max_length=255)
    owner_kind: Literal["user", "team"]
    owner_uuid: UUID
    permissions: tuple[Literal["use_resources", "approve_agent_session"], ...]


class _PlatformCurrent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str
    subject: str
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    user_uuid: UUID
    enabled: bool
    role: Literal["user", "operator"]
    directory_paged: bool = False
    expires_at: datetime
    teams: tuple[_Team, ...]
    projects: tuple[_Project, ...]

    def projection(self) -> ResolvedPlatformUser:
        return ResolvedPlatformUser(
            issuer=self.issuer,
            subject=self.subject,
            user_uuid=self.user_uuid,
            enabled=self.enabled,
            role=self.role,
            expires_at=self.expires_at,
            name=self.name,
            email=self.email,
            directory_paged=self.directory_paged,
            teams=tuple(
                PlatformTeamContext(item.team_uuid, item.owner, item.name, item.member)
                for item in self.teams
            ),
            projects=tuple(
                PlatformProjectContext(
                    item.project_uuid, item.owner_kind, item.owner_uuid, item.permissions, item.name
                )
                for item in self.projects
            ),
        )


class HttpPlatformProjection:
    def __init__(
        self,
        connection: VerifiedPlatformServiceTransport,
        delegation: VerifiedPanelDelegation,
        query: PlatformProjectionQuery,
    ) -> None:
        self._connection = connection
        self._query = query
        self.authority = PlatformProjectionAuthority(
            connection.mode,
            connection.server_audience,
            connection.expires_at,
            delegation.issuer,
            delegation.subject,
            delegation.project_uuid,
            delegation.recipient,
            delegation.expires_at,
            delegation.bearer,
        )

    async def read(self) -> ResolvedPlatformUser | None:
        payload = {"issuer": self._query.issuer, "subject": self._query.subject}
        if self._query.project_uuid is not None:
            payload["project_uuid"] = str(self._query.project_uuid)
        try:
            async with self._connection.client.stream(
                "POST",
                _OWNER_URL,
                json=payload,
                follow_redirects=False,
                headers={
                    "Authorization": "Bearer " + self.authority.bearer.get_secret_value(),
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            ) as response:
                raw = await _read_response(response)
        except (httpx.HTTPError, TimeoutError):
            raise PlatformProjectionInvalid("private Platform transport unavailable") from None
        if raw is None:
            return None
        try:
            return _PlatformCurrent.model_validate_json(raw).projection()
        except ValueError:
            raise PlatformProjectionInvalid("Platform response invalid") from None


async def _read_response(response: httpx.Response) -> bytes | None:
    if response.status_code == 403:
        return None
    if response.status_code != 200:
        raise PlatformProjectionInvalid("private Platform owner not available")
    if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise PlatformProjectionInvalid("Platform owner returned non-JSON")
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > 32768:
            raise PlatformProjectionInvalid("Platform owner response too large")
        body.extend(chunk)
    return bytes(body)


class AttestedPlatformProjectionPeer(_PeerBinding[TrustedPlatformPeerPort]):
    async def open(self, query: PlatformProjectionQuery) -> PlatformProjectionChannel:
        connection = await self._peer.current_transport()
        if query.project_uuid is None:
            delegation = await self._peer.signed_subject_delegation(
                issuer=query.issuer, subject=query.subject
            )
        else:
            delegation = await self._peer.signed_project_delegation(
                issuer=query.issuer, subject=query.subject, project_uuid=query.project_uuid
            )
        return HttpPlatformProjection(
            _checked_transport(connection), _checked_delegation(delegation), query
        )
