"""Cookie-authenticated Briareus Platform context, distinct from Rauthy identity.

Only a real trusted Platform owner adapter may bind an external Rauthy subject
to a current active Briareus User and visible Team/Project memberships.
The Control Panel API never infers Briareus privileges from OAuth claims.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.requests import HTTPConnection

from control_panel_api.domain.platform_authority import PanelOidcSession
from control_panel_api.presentation._http_errors import error_response

from ._api_paths import AUTH_API_PREFIX
from ._oidc_browser import OidcBrowserSessionStore
from ._oidc_origin_policy import PUBLIC_ORIGIN, local_browser_host, resolve_browser_origin
from .application.platform_membership import CurrentMembership
from .application.platform_membership import CurrentPlatformUserSource as CurrentPlatformUserSource
from .application.platform_membership import (
    PlatformMembershipUnavailable as PlatformMembershipUnavailable,
)
from .application.platform_projection import platform_context_payload
from .presentation.platform_membership import MembershipController

if TYPE_CHECKING:
    from runtime_peer import PeerClient

    from ._oidc_catalog import TrustedCatalogReadPort
    from ._oidc_files_content import TrustedFilesContentOwner
    from ._platform_unix_peer import UnixPlatformPeer
    from .application.approval_contracts import ApprovalSource


from .domain.platform_authority import (
    PlatformProjectContext as PlatformProjectContext,
)
from .domain.platform_authority import (
    PlatformTeamContext as PlatformTeamContext,
)
from .domain.platform_authority import (
    ResolvedPlatformUser as ResolvedPlatformUser,
)

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class CurrentPlatformContext(Protocol):
    async def __call__(
        self, request: HTTPConnection, project_uuid: UUID | None = None
    ) -> tuple[PanelOidcSession, ResolvedPlatformUser] | JSONResponse: ...


def platform_membership_router(
    sessions: OidcBrowserSessionStore,
    *,
    source: CurrentPlatformUserSource | None,
    approval_source: ApprovalSource | None = None,
    catalog_source: TrustedCatalogReadPort | None = None,
    files_content_source: TrustedFilesContentOwner | None = None,
    resource_audience: str | None = None,
    test_only_local_origin: str | None = None,
    expected_issuer: str | None = None,
    expected_client_id: str | None = None,
    management_peer: UnixPlatformPeer | None = None,
    terminal_peer: PeerClient | None = None,
    files_peer: PeerClient | None = None,
    web_peer: PeerClient | None = None,
    connections_peer: PeerClient | None = None,
) -> APIRouter:
    expected_host = local_browser_host(test_only_local_origin)
    router = APIRouter()

    fail = error_response

    current_context = MembershipController(
        CurrentMembership(
            sessions, source, expected_issuer=expected_issuer, expected_client_id=expected_client_id
        ),
        expected_host=expected_host,
    )

    async def read_current_user(
        request: HTTPConnection, project_uuid: UUID | None = None
    ) -> JSONResponse:
        if request.query_params and (
            set(request.query_params) != {"project_uuid"}
            or len(request.query_params.getlist("project_uuid")) != 1
            or project_uuid is None
            or project_uuid.version != 4
            or request.query_params["project_uuid"] != str(project_uuid)
        ):
            return fail(422, "PLATFORM_PROJECT_INVALID")
        context = await current_context(request, project_uuid)
        if isinstance(context, JSONResponse):
            return context
        session, proof = context
        return JSONResponse(asdict(platform_context_payload(session, proof)), headers=_NO_STORE)

    @router.get(AUTH_API_PREFIX + "/me")
    async def current_user(request: Request, project_uuid: UUID | None = None) -> JSONResponse:
        return await read_current_user(request, project_uuid)

    from ._panel_events import panel_events_router
    from ._runtime_access_client import RuntimeAccessClient

    router.include_router(
        panel_events_router(
            current_context=current_context,
            current_user=read_current_user,
            access=approval_source if isinstance(approval_source, RuntimeAccessClient) else None,
            platform=management_peer,
            resources=connections_peer,
        )
    )

    from ._platform_management import platform_management_router

    router.include_router(
        platform_management_router(
            current_context=current_context,
            peer=management_peer,
            browser_origin=resolve_browser_origin(
                test_origin=test_only_local_origin,
                provider_issuer=expected_issuer,
                provider_client=expected_client_id,
            )
            if expected_issuer and expected_client_id
            else PUBLIC_ORIGIN,
        )
    )

    # Imported only after the identity DTO is defined to avoid cyclic
    # module initialization; approval endpoints share the exact same proof.
    from .presentation.approval_controller import approval_management_router

    router.include_router(
        approval_management_router(
            current_context=current_context,
            owner=approval_source,
            test_only_local_origin=test_only_local_origin,
        )
    )
    if terminal_peer is not None:
        from ._runtime_terminal import terminal_runtime_router

        if not isinstance(approval_source, RuntimeAccessClient):
            raise ValueError("Terminal requires the independently authenticated Access owner")
        router.include_router(
            terminal_runtime_router(
                current_context=current_context,
                access=approval_source,
                terminal=terminal_peer,
                files=files_peer,
                web=web_peer,
            )
        )

    from ._oidc_connections import connection_router

    router.include_router(connection_router(current_context=current_context, peer=connections_peer))

    from ._oidc_catalog import oidc_catalog_router

    router.include_router(
        oidc_catalog_router(current_context=current_context, catalog=catalog_source)
    )
    from ._oidc_files_content import files_content_router

    router.include_router(
        files_content_router(
            current_context=current_context,
            sessions=sessions,
            resource_audience=resource_audience,
            expected_client_id=expected_client_id,
            owner=files_content_source,
            test_only_local_origin=test_only_local_origin,
        )
    )
    return router
