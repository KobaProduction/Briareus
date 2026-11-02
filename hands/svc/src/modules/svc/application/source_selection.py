"""Select a provider source only after original-scope, C2 and fresh-grant checks."""

from datetime import UTC as UTC
from datetime import datetime as datetime
from typing import Protocol as Protocol

from modules.project_runtime.application.resource_authority import (
    ResourceAuthorityPort as ResourceAuthorityPort,
)
from modules.project_runtime.domain.authorization import ProjectInvocation as ProjectInvocation
from modules.svc.domain.source_selection import _SOURCE_RULES
from modules.svc.domain.source_selection import SVC_SOURCE_HANDLERS as SVC_SOURCE_HANDLERS
from modules.svc.domain.source_selection import SVCAction as SVCAction
from modules.svc.domain.source_selection import SVCProvider as SVCProvider
from modules.svc.domain.source_selection import SVCSourceSelection as SVCSourceSelection
from modules.svc.domain.source_selection import SVCUnavailable as SVCUnavailable
from modules.svc.domain.source_selection import VerifiedSVCPeer as VerifiedSVCPeer
from modules.svc.domain.source_selection import require_initial_grant as require_initial_grant
from modules.svc.domain.source_selection import require_original_scope as require_original_scope
from modules.svc.domain.source_selection import require_refreshed_grant as require_refreshed_grant
from source_control.application.source_selection import (
    PrivateSVCSourceSelector as _PrivateSVCSourceSelector,
)


class TrustedSVCServiceSourcePort(Protocol):
    async def require_current_service_source(
        self, invocation: ProjectInvocation, *, provider: SVCProvider, action: SVCAction
    ) -> VerifiedSVCPeer: ...


class PrivateSVCSourceSelector(_PrivateSVCSourceSelector[VerifiedSVCPeer, SVCSourceSelection]):
    _rules = _SOURCE_RULES
    _peer_type = VerifiedSVCPeer
    _selection_type = SVCSourceSelection
    _source_handler = staticmethod(lambda provider: SVC_SOURCE_HANDLERS[provider])
