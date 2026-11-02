"""One fail-closed SVC source selection sequence; local roots supply nominal classes."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from project_runtime_client.application.resource_authority import ResourceAuthorityPort
from project_runtime_client.domain.authorization import ProjectInvocation
from source_control.domain.source_selection import (
    SourceSelectionRules,
    SVCAction,
    SVCProvider,
    SVCSourceSelection,
    VerifiedSVCPeer,
)


class TrustedSVCServiceSourcePort[PeerT: VerifiedSVCPeer](Protocol):
    async def require_current_service_source(
        self, invocation: ProjectInvocation, *, provider: SVCProvider, action: SVCAction
    ) -> PeerT: ...


class PrivateSVCSourceSelector[PeerT: VerifiedSVCPeer, SelectionT: SVCSourceSelection]:
    authority: ResourceAuthorityPort
    service_source: TrustedSVCServiceSourcePort[PeerT] | None
    _rules: SourceSelectionRules[PeerT]
    _peer_type: type[PeerT]
    _selection_type: type[SelectionT]
    _source_handler: Callable[[SVCProvider], tuple[str, str]]

    def __init__(
        self,
        authority: ResourceAuthorityPort,
        *,
        service_source: TrustedSVCServiceSourcePort[PeerT] | None = None,
    ) -> None:
        self.authority = authority
        self.service_source = service_source

    async def require_source(
        self, invocation: ProjectInvocation, *, provider: SVCProvider, action: SVCAction
    ) -> SelectionT:
        scope = self._rules.require_original_scope(
            invocation,
            provider=provider,
            action=action,
            service_source_available=self.service_source is not None,
        )
        initial = await self.authority.require(invocation, action)
        self._rules.require_initial_grant(initial, now=datetime.now(UTC))
        try:
            source = self.service_source
            if source is None:
                raise self._rules.unavailable("SVC_SIGNED_SERVICE_SOURCE_UNAVAILABLE")
            peer = await source.require_current_service_source(
                invocation, provider=provider, action=action
            )
        except Exception as exc:
            raise self._rules.unavailable("SVC_SIGNED_SERVICE_SOURCE_UNAVAILABLE") from exc
        if not isinstance(peer, self._peer_type):
            raise self._rules.unavailable("SVC_VERIFIED_PEER_SCOPE_CHANGED")
        peer.require_for(initial, scope, provider=provider, action=action, now=datetime.now(UTC))
        refreshed = await self.authority.require(invocation, action)
        self._rules.require_refreshed_grant(
            initial,
            refreshed,
            peer,
            grant_observed_at=datetime.now(UTC),
            peer_observed_at=datetime.now(UTC),
        )
        module_name, handler = self._source_handler(provider)
        if handler != "mcp":
            raise self._rules.unavailable("SVC_SOURCE_HANDLER_NOT_REVIEWED")
        return self._selection_type(
            provider=provider,
            module_name=module_name,
            handler_name="mcp",
            operation_uuid=scope.request_uuid,
            recipient_service_id=peer.service_id,
            recipient_instance_uuid=peer.instance_uuid,
        )
