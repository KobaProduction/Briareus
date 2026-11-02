"""Adapt Rauthy bearer verification and authenticated current Platform facts."""

from datetime import UTC, datetime
from typing import NamedTuple, Protocol
from uuid import UUID

from authorization._rauthy_issuer_keys import TrustedRauthyIssuerKeys
from authorization._rauthy_jwks import VerifiedRauthySubject
from authorization.domain.mcp_identity import ProjectContextLookupFailed, bind_current_identity
from authorization.domain.runtime_policy import RuntimeActor
from authorization.domain.workspace_effects import WorkspaceIdentity
from authorization.presentation.runtime_protocol import ActorContext
from runtime_peer import PeerClient
from runtime_peer.response_decoding import successful_reply


class CurrentIdentityResolution(NamedTuple):
    actor: ActorContext
    signed: VerifiedRauthySubject


class CurrentIdentityResolver(Protocol):
    async def __call__(
        self,
        *,
        platform: PeerClient,
        actor_model: type[ActorContext],
        keys: TrustedRauthyIssuerKeys,
        bearer: str,
        project_uuid: UUID,
    ) -> CurrentIdentityResolution: ...


async def resolve_current_identity(
    *,
    platform: PeerClient,
    actor_model: type[ActorContext],
    keys: TrustedRauthyIssuerKeys,
    bearer: str,
    project_uuid: UUID,
) -> CurrentIdentityResolution:
    verifier = await keys.get_verifier()
    signed = verifier.verify_access_token(bearer)
    _owner_reply = await platform.call(
        "/internal/v1/platform/oidc/actor-context",
        {
            "issuer": signed.issuer,
            "subject": signed.subject,
            "project_uuid": str(project_uuid),
        },
        decode=successful_reply(actor_model.model_validate),
    )
    status, context = _owner_reply.status, _owner_reply.body
    if status != 200 or context is None:
        raise ProjectContextLookupFailed(status)
    actor = context
    bind_current_identity(
        RuntimeActor(
            actor.issuer,
            actor.subject,
            actor.actor_uuid,
            actor.project_uuid,
            actor.expires_at,
            actor.permissions,
            actor.role,
        ),
        issuer=signed.issuer,
        subject=signed.subject,
        provider_expires_at=signed.expires_at,
        project_uuid=project_uuid,
        now=datetime.now(UTC),
    )
    return CurrentIdentityResolution(actor, signed)


class PeerWorkspaceIdentity:
    def __init__(
        self,
        *,
        platform: PeerClient,
        actor_model: type[ActorContext],
        keys: TrustedRauthyIssuerKeys,
        bearer: str,
        project_uuid: UUID,
        resolver: CurrentIdentityResolver,
    ) -> None:
        self.platform = platform
        self.actor_model = actor_model
        self.keys = keys
        self.bearer = bearer
        self.project_uuid = project_uuid
        self.resolver = resolver

    async def current(self) -> WorkspaceIdentity:
        actor, signed = await self.resolver(
            platform=self.platform,
            actor_model=self.actor_model,
            keys=self.keys,
            bearer=self.bearer,
            project_uuid=self.project_uuid,
        )
        return WorkspaceIdentity(
            signed.issuer, signed.subject, actor.actor_uuid, actor.expires_at, signed.expires_at
        )
