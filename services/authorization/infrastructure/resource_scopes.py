"""Decode persisted JSONB selectors into canonical owner facts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from authorization.application.access_inputs import _ScopeGrantProjection
from authorization.application.resource_receipts import EffectResource, VerifiedResourceOwnerProof
from authorization.domain.action_audiences import HAND_EFFECT_AUDIENCES
from authorization.domain.resource_scopes import ResourceSelector, canonical_grants
from authorization.domain.sessions import SessionResourceGrant
from common.platform_ids import PlatformProjectId


class _StoredScope(BaseModel, _ScopeGrantProjection[str, EffectResource]):
    model_config = ConfigDict(strict=True)

    hand: str
    tool: str
    action: str
    resource: EffectResource


class _ProofEnvelope(BaseModel):
    model_config = ConfigDict(strict=True, from_attributes=True)

    project_uuid: UUID
    revision: int
    expires_at: datetime


def _decode_scope(item: Mapping[str, object]) -> SessionResourceGrant:
    return _StoredScope.model_validate(item).domain()


def decode_resource_grants(raw: object) -> tuple[SessionResourceGrant, ...]:
    if not isinstance(raw, list) or len(raw) > 32:
        raise ValueError("resource grants must be a bounded list")
    decoded: list[SessionResourceGrant] = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"hand", "tool", "action", "resource"}:
            raise ValueError("resource grant shape invalid")
        decoded.append(_decode_scope(item))
    return tuple(decoded)


def normalized_resource_grants(
    requested: object,
    *,
    allowed_actions: set[str],
    project_uuid: UUID | None = None,
) -> tuple[SessionResourceGrant, ...]:
    return canonical_grants(decode_resource_grants(requested), allowed_actions, project_uuid)


def stored_grant_matches(
    *,
    stored: tuple[SessionResourceGrant, ...] | None,
    hand: str,
    tool: str,
    action: str,
    resource: EffectResource,
    project_uuid: UUID | None = None,
) -> bool:
    if stored is None or not stored:
        return False
    try:
        requested = SessionResourceGrant(hand, tool, action, resource.kind, resource.id)
        canonical_grants((requested,), {action}, project_uuid)
        grants = canonical_grants(
            stored,
            set(HAND_EFFECT_AUDIENCES),
            project_uuid,
            unique=False,
        )
        return requested in grants
    except (ValueError, TypeError):
        return False


def matches_current_owner(
    proof: VerifiedResourceOwnerProof | None,
    *,
    project_uuid: PlatformProjectId,
    scope: SessionResourceGrant,
) -> bool:
    if not isinstance(proof, VerifiedResourceOwnerProof):
        return False
    try:
        _ProofEnvelope.model_validate(proof)
        canonical_grants((scope,), {scope.action}, project_uuid)
        return proof.matches(scope, project_uuid, datetime.now(UTC))
    except (KeyError, ValueError, TypeError):
        return False


def validate_resource_scope(hand: str, tool: str, resource: EffectResource) -> None:
    resource.selector().validate(hand, tool)


def validate_project_resource_scope(
    *,
    project_uuid: UUID,
    hand: str,
    tool: str,
    resource: EffectResource,
) -> None:
    resource.selector().require_project(project_uuid, hand, tool)


def validate_effect_scope(hand: str, tool: str, action: str, resource: EffectResource) -> None:
    resource.selector().validate(hand, tool, action)


def resource_key(hand: str, tool: str, resource: EffectResource) -> str:
    return ResourceSelector(resource.kind, resource.id).key(hand, tool)
