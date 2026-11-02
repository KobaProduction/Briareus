"""Authenticated resource snapshots, Access SQL grant locks and local permit signing."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel, Field, StrictBool, StrictInt, StrictStr, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._access_cedar import permits_current_project_grant
from authorization._resource_scope import EffectResource, HandName
from authorization._runtime_resource_owners import CurrentRuntimeResourceOwners
from authorization._session_persistence import ProjectAgentSessionRow
from authorization.application.runtime_dispatch import RuntimePermit
from authorization.application.runtime_effects import (
    RuntimeEffectCall,
    RuntimeEffectConfig,
    RuntimeEffectPreparation,
    RuntimeGrant,
    RuntimeGrantTransaction,
)
from authorization.application.runtime_inputs import RuntimeResourceQuery
from authorization.domain.runtime_policy import RuntimeAccessDenied, RuntimeActor, RuntimePlacement
from authorization.infrastructure.runtime_handlers import RuntimePeers
from common.platform_db import PlatformDatabase
from common.platform_errors import AccessDenied, InvalidInput
from node_protocol.module_effects import MODULES, RESOURCE_KINDS, effect_action
from runtime_peer.effect_permit import PrivateEffectClaims
from runtime_peer.response_decoding import successful_reply
from runtime_peer.runtime_resource_receipts import (
    RuntimeResource,
    RuntimeResourceItem,
    RuntimeResources,
    RuntimeResourceSelector,
)
from service_runtime.platform_db_mechanics import _PrivateDatabaseBinding


class PlacementReply(BaseModel):
    project_uuid: StrictStr
    isolated: StrictBool
    resource_id: StrictStr
    resource_revision: StrictInt
    tools: tuple[StrictStr, ...] = Field(min_length=1, max_length=32)


class PeerRuntimePlacements:
    def __init__(self, peers: RuntimePeers) -> None:
        self._peers = peers

    async def inspect(self, actor: RuntimeActor, hand: str) -> RuntimePlacement:
        owner = {
            "terminal": self._peers.terminal,
            "files": self._peers.files,
            "web": self._peers.web,
        }.get(hand)
        if owner is None:
            raise RuntimeAccessDenied("Runtime resource owner not connected")
        try:
            _owner_reply = await owner.call(
                "/internal/v1/" + hand + "/inspect",
                {},
                decode=successful_reply(PlacementReply.model_validate),
            )
        except ValidationError:
            raise RuntimeAccessDenied("Current Terminal placement not verified") from None
        status, raw = _owner_reply.status, _owner_reply.body
        if status != 200 or raw is None:
            raise RuntimeAccessDenied("Current Terminal placement not verified")
        placement = raw
        if placement.project_uuid != str(actor.project_uuid):
            raise RuntimeAccessDenied("Current Terminal placement not verified")
        return RuntimePlacement(
            hand,
            actor.project_uuid,
            placement.isolated,
            placement.resource_id,
            placement.resource_revision,
            placement.tools,
        )


class SqlRuntimeGrantUnitOfWork(_PrivateDatabaseBinding[PlatformDatabase]):
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[RuntimeGrantTransaction]:
        async with self._database.transaction() as tx:
            yield SqlRuntimeGrant(tx)


class SqlRuntimeGrant:
    def __init__(self, transaction: AsyncSession) -> None:
        self._transaction = transaction

    async def require_grant(
        self,
        actor: RuntimeActor,
        placement: RuntimePlacement,
        call: RuntimeEffectCall,
        config: RuntimeEffectConfig,
    ) -> RuntimeGrant:
        hand: HandName
        if placement.hand == "files":
            hand = "files"
        elif placement.hand == "terminal":
            hand = "terminal"
        elif placement.hand == "web":
            hand = "web"
        else:
            raise RuntimeAccessDenied("Runtime resource owner not connected")
        row = await self._transaction.scalar(
            select(ProjectAgentSessionRow)
            .where(
                ProjectAgentSessionRow.session_uuid == call.agent_session_uuid,
                ProjectAgentSessionRow.project_id == actor.project_uuid,
            )
            .with_for_update()
        )
        resource = EffectResource(kind=config.kind, id=placement.resource_id)
        if row is None or not permits_current_project_grant(
            row=row,
            actor_uuid=actor.actor_uuid,
            project_uuid=actor.project_uuid,
            operation=config.action,
            expected_version=call.expected_grant_revision,
            hand=hand,
            tool=call.tool,
            resource=resource,
        ):
            raise AccessDenied("Current Cedar Terminal grant required")
        return RuntimeGrant(row.hard_expires_at)


class JwtRuntimeEffectSigner:
    def __init__(self, key: Ed25519PrivateKey | None) -> None:
        self._key = key

    @property
    def configured(self) -> bool:
        return self._key is not None

    def sign(
        self,
        actor: RuntimeActor,
        placement: RuntimePlacement,
        call: RuntimeEffectCall,
        config: RuntimeEffectConfig,
        *,
        issued_at: int,
        expires_at: int,
    ) -> str:
        if self._key is None:
            raise ValueError("Invalid terminal effect")
        return jwt.encode(
            PrivateEffectClaims(
                aud=config.audience,
                iat=issued_at,
                nbf=issued_at,
                exp=expires_at,
                jti=uuid4(),
                project_uuid=actor.project_uuid,
                actor_uuid=actor.actor_uuid,
                session_uuid=call.agent_session_uuid,
                grant_revision=call.expected_grant_revision,
                tool=call.tool,
                arguments_digest=call.arguments_digest,
                resource_id=placement.resource_id,
                resource_revision=placement.resource_revision,
                operation_uuid=call.operation_uuid,
            ).model_dump(mode="json"),
            self._key,
            algorithm="EdDSA",
            headers={"typ": "briareus-effect-permit+jwt"},
        )


class RuntimeResourceHandlers:
    def __init__(self, peers: RuntimePeers, preparation: RuntimeEffectPreparation) -> None:
        self._peers = peers
        self._preparation = preparation

    async def prepare(
        self, actor: RuntimeActor, hand: str, command: RuntimeEffectCall
    ) -> RuntimePermit:
        return await self._preparation.prepare(actor, hand, command)

    async def catalogue(
        self, actor: RuntimeActor, command: RuntimeResourceQuery
    ) -> RuntimeResources:
        hand = command.hand
        peer = self._peers.node_resources
        if hand not in MODULES or peer is None:
            raise InvalidInput("Current Node resource owner unavailable")
        binding = await CurrentRuntimeResourceOwners.node_workspace(peer, actor.project_uuid, hand)
        tools = self._tools(hand)
        return RuntimeResources(
            items=tuple(
                RuntimeResourceItem(
                    hand=hand,
                    tool=tool,
                    action=effect_action(hand, tool),
                    resource=RuntimeResourceSelector(
                        kind=RESOURCE_KINDS[hand], id=binding.resource_id
                    ),
                )
                for tool in sorted(tools or ())
            ),
            resource=RuntimeResource(hand=hand, kind=RESOURCE_KINDS[hand], id=binding.resource_id),
            catalogue_state="static" if tools is not None else "not_described",
            expires_at=min(
                actor.expires_at, datetime.fromtimestamp(binding.expires_at, UTC)
            ).isoformat(),
        )

    @staticmethod
    def _tools(hand: str) -> frozenset[str] | None:
        if hand == "files":
            from node_protocol import files

            return files.READ_TOOLS | getattr(files, "WRITE_TOOLS", frozenset())
        if hand == "terminal":
            from node_protocol.terminal import TOOLS

            return TOOLS
        return None
