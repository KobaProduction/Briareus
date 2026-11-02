"""Provider identity, current Resources scope and human-only Cedar adapters."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from authorization._rauthy_issuer_keys import TrustedRauthyIssuerKeys
from authorization.domain.human_web import HumanIdentity, HumanResource
from authorization.domain.workspace_effects import WorkspaceBinding, WorkspaceIdentity
from authorization.infrastructure.mcp_identity import resolve_current_identity
from authorization.infrastructure.workspace_effects import current_workspace_binding
from authorization.presentation.runtime_protocol import ActorContext
from node_protocol.module_effects import RESOURCE_KINDS, effect_action
from runtime_peer import PeerClient
from runtime_peer.human_scope import HumanScopeReceipt
from runtime_peer.response_decoding import successful_reply


@dataclass(frozen=True, slots=True)
class CurrentHumanIdentity:
    platform: PeerClient
    actor_model: type[ActorContext]
    keys: TrustedRauthyIssuerKeys
    bearer: str = field(repr=False)
    project_uuid: UUID

    async def current(self) -> HumanIdentity:
        actor, signed = await resolve_current_identity(
            platform=self.platform,
            actor_model=self.actor_model,
            keys=self.keys,
            bearer=self.bearer,
            project_uuid=self.project_uuid,
        )
        return HumanIdentity(
            WorkspaceIdentity(
                signed.issuer, signed.subject, actor.actor_uuid, actor.expires_at, signed.expires_at
            ),
            actor.project_uuid,
            actor.permissions,
        )


@dataclass(frozen=True, slots=True)
class CurrentHumanBinding:
    resources: PeerClient
    project_uuid: UUID
    module: Literal["web", "files", "terminal", "reverse"] = "web"

    async def current(self) -> WorkspaceBinding:
        return await current_workspace_binding(self.resources, self.module, self.project_uuid)


@dataclass(frozen=True, slots=True)
class CurrentHumanResource:
    resources: PeerClient
    module: Literal["web", "files", "terminal", "reverse"] = "web"

    async def current(self, identity: HumanIdentity, binding: WorkspaceBinding) -> HumanResource:
        subject = identity.identity
        owner = await self.resources.call(
            "/internal/v1/resources/"
            + {"web": "browser", "files": "files", "terminal": "terminal", "reverse": "analysis"}[
                self.module
            ]
            + "-scope",
            {
                "issuer": subject.issuer,
                "subject": subject.subject,
                "actor_uuid": str(subject.actor_uuid),
                "project_uuid": str(identity.project_uuid),
                "identity_expires_at": min(
                    subject.actor_expires_at, subject.provider_expires_at
                ).isoformat(),
            },
            decode=successful_reply(HumanScopeReceipt.model_validate),
        )
        if owner.status != 200 or owner.body is None:
            raise PermissionError("Human browser scope unavailable")
        if any(
            item.hand != self.module
            or item.action != effect_action(self.module, item.tool)
            or item.resource.kind != RESOURCE_KINDS[self.module]
            or item.resource.id != binding.resource_id
            for item in owner.body.items
        ):
            raise PermissionError("Human browser scope differs from current placement")
        identity.require_current(binding.project_uuid, datetime.now(UTC))
        return HumanResource(binding.resource_id, frozenset(item.tool for item in owner.body.items))
