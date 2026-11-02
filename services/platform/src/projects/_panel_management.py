"""Human Platform administration over the authenticated Panel peer only.

Rauthy owns profiles, credentials and the administrator designation. Platform
membership is provisioned on authenticated access; no manual linking here.
Writes, idempotency evidence, audit and outbox commit in one owner transaction.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import TypeAdapter, ValidationError

from common.platform_db import PlatformDatabase
from projects.application.events import PlatformEventQuery, ReadPlatformEvents
from projects.domain.agents import AgentDetail, AgentPage
from projects.domain.directory import DirectoryPage
from projects.domain.inventory import Inventory, UserProfile
from projects.domain.invitations import InvitationCapabilities, InvitationOutcome, InviterOutcome
from projects.domain.management import ManagementError, ManagementOutcome
from projects.domain.management import identifier as identifier
from projects.domain.management import name as name
from projects.infrastructure.events import SqlPlatformEventReader
from projects.infrastructure.invitation_provider import InvitationLookupTransport
from projects.presentation.management_inputs import (
    MANAGEMENT_QUERY,
    AgentGetQuery,
    AgentListQuery,
    DirectoryQuery,
    EventsQuery,
    InventoryQuery,
    InvitationCapabilitiesQuery,
    IssueInvitationQuery,
    ManagementQuery,
    SetInviterQuery,
    TeamReadQuery,
)
from runtime_peer.event_projection import EventPage

from ._oidc_context_api import PanelContextNotAuthenticated
from ._oidc_membership_projection import PlatformOidcMembershipProjection
from ._rauthy_user_status import CurrentRauthyUserStatusReader, RauthyUserPrivateTransport

HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class AdministrationProvider(RauthyUserPrivateTransport, InvitationLookupTransport, Protocol):
    pass


class ManagementAuthority(Protocol):
    async def verify_management(self, request: Request, query: ManagementQuery) -> datetime: ...


ManagementResult = (
    DirectoryPage
    | EventPage
    | ManagementOutcome
    | Inventory
    | AgentDetail
    | AgentPage
    | InvitationCapabilities
    | InvitationOutcome
    | InviterOutcome
)


MANAGEMENT_RESULT = TypeAdapter[ManagementResult](ManagementResult)


class ManagementService(Protocol):
    async def execute(self, query: ManagementQuery, deadline: datetime) -> ManagementResult: ...


class PlatformAdministration:
    def __init__(
        self,
        database: PlatformDatabase,
        projection: PlatformOidcMembershipProjection,
        provider: AdministrationProvider,
    ) -> None:
        self.db, self.projection, self.provider = database, projection, provider
        self.status = CurrentRauthyUserStatusReader(private_transport=provider)

    async def profile(self, issuer: str, subject: str) -> UserProfile:
        status = await self.status.current_status(issuer=issuer, subject=subject)
        return UserProfile(status.name, status.email, status.active)

    async def execute(
        self, query: ManagementQuery, deadline: datetime
    ) -> (
        DirectoryPage
        | EventPage
        | ManagementOutcome
        | Inventory
        | AgentDetail
        | AgentPage
        | InvitationCapabilities
        | InvitationOutcome
        | InviterOutcome
    ):
        actor = await self.projection.resolve(issuer=query.issuer, subject=query.subject)
        if actor is None:
            raise ManagementError(403, "PLATFORM_OPERATOR_REQUIRED")
        deadline = min(deadline, actor.expires_at)
        if isinstance(query, (InvitationCapabilitiesQuery, IssueInvitationQuery, SetInviterQuery)):
            from ._panel_invitations import execute_invitations

            return await execute_invitations(self, query, actor, deadline)
        if isinstance(query, (AgentListQuery, AgentGetQuery)):
            from ._panel_agents import read_agents

            return await read_agents(self, query, actor, deadline)
        if isinstance(query, DirectoryQuery):
            from ._panel_directory import read_directory

            return await read_directory(self, query, actor, deadline)
        if isinstance(query, TeamReadQuery):
            from ._panel_team_read import read_team

            return await read_team(self, query, actor, deadline)
        if isinstance(query, EventsQuery):
            visible = (
                None
                if actor.role == "operator"
                else (
                    tuple(str(team.team_id) for team in actor.teams)
                    + tuple(str(project.project_id) for project in actor.projects)
                )
            )
            use_case = ReadPlatformEvents(
                SqlPlatformEventReader(self.db), lambda: datetime.now(UTC)
            )
            return await use_case.execute(
                PlatformEventQuery(query.data.window(), visible), deadline
            )
        if actor.role != "operator":
            raise ManagementError(403, "PLATFORM_OPERATOR_REQUIRED")
        if isinstance(query, InventoryQuery):
            from projects._inventory_composition import read_inventory

            return await read_inventory(self, query, actor, deadline)

        from projects._management_mutations import manage

        return await manage(self.db, query, actor.user_id, query.fingerprint(), deadline)


async def management_query(request: Request) -> ManagementQuery:
    if (
        request.scope.get("briareus.unix_peer_uid") != 1001
        or request.headers.getlist("cookie")
        or len(request.headers.getlist("authorization")) != 1
    ):
        raise ManagementError(401, "PLATFORM_SERVICE_PROOF_REQUIRED")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 8192:
            raise ManagementError(413, "COMMAND_TOO_LARGE")
    return MANAGEMENT_QUERY.validate_json(body)


def management_router(
    resolve_service: Callable[[], ManagementService | None],
    authority: ManagementAuthority | None,
) -> APIRouter:
    router = APIRouter()

    @router.post("/internal/v1/platform/manage", include_in_schema=False)
    async def manage(request: Request) -> Response:
        try:
            service = resolve_service()
            if service is None or authority is None:
                raise ManagementError(503, "PLATFORM_MANAGEMENT_UNAVAILABLE")
            query = await management_query(request)
            deadline = await authority.verify_management(request, query)
            result = await service.execute(query, deadline)
            return Response(
                MANAGEMENT_RESULT.dump_json(result), media_type="application/json", headers=HEADERS
            )
        except ManagementError as error:
            return JSONResponse(
                {"error": {"code": error.code}}, status_code=error.status, headers=HEADERS
            )
        except PanelContextNotAuthenticated:
            return JSONResponse(
                {"error": {"code": "PLATFORM_SERVICE_PROOF_REQUIRED"}},
                status_code=401,
                headers=HEADERS,
            )
        except ValidationError:
            return JSONResponse(
                {"error": {"code": "COMMAND_INVALID"}}, status_code=422, headers=HEADERS
            )
        except Exception:
            return JSONResponse(
                {"error": {"code": "PLATFORM_MANAGEMENT_UNAVAILABLE"}},
                status_code=503,
                headers=HEADERS,
            )

    return router
