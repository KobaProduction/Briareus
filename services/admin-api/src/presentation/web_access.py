"""Retained access HTTP adapters with focused dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from application.web_session_contracts import (
    WebAccessRequests,
    WebAccessSessions,
    WebSessionRevoked,
    WebSurfaceControls,
    WebUserControls,
    WebUserView,
)
from fastapi import APIRouter, HTTPException, Request
from infrastructure.authorization_access import AuthorizationAccessAdminClient
from realtime import RealtimeBus
from starlette.responses import Response

from common.access_contracts import (
    ResolvedAccessRequest,
    SessionSnapshot,
)
from presentation.web_admission import WebAdmission
from presentation.web_models import (
    AccessControlBatchPayload,
    AccessResolvePayload,
    AccessSessionUpdatePayload,
)


@dataclass(frozen=True, slots=True)
class WebAccessServices:
    realtime: RealtimeBus | None
    authorization_access: AuthorizationAccessAdminClient | None


@dataclass(eq=False, repr=False)
class WebAccessController:
    admission: WebAdmission
    services: WebAccessServices | None

    def mount(self, router: APIRouter) -> None:
        router.get("/access/sessions")(self.access_sessions)
        router.get("/access/requests")(self.access_requests)
        router.get("/access/controls")(self.access_controls)
        router.post("/access/requests/{request_id}/resolve")(self.resolve_access_request)
        router.patch("/access/sessions/{session_id}")(self.update_access_session)
        router.post("/access/sessions/{session_id}/revoke", status_code=204)(
            self.revoke_access_session
        )
        router.put("/access/controls")(self.update_access_controls)

    def authorization_access_control(
        self, api: WebAccessServices
    ) -> AuthorizationAccessAdminClient:
        if api.authorization_access is None:
            raise HTTPException(status_code=503, detail="authorization controls unavailable")
        return api.authorization_access

    async def access_sessions(self, request: Request) -> WebAccessSessions:
        identity = await self.admission.local_user(request)
        api = self.admission.available(self.services)
        sessions = await self.authorization_access_control(api).sessions(identity.id)
        return WebAccessSessions(user=WebUserView.from_record(identity), sessions=sessions)

    async def access_requests(self, request: Request) -> WebAccessRequests:
        identity = await self.admission.local_user(request)
        api = self.admission.available(self.services)
        requests = await self.authorization_access_control(api).requests(identity.id)
        return WebAccessRequests(user=WebUserView.from_record(identity), requests=requests)

    async def access_controls(self, request: Request) -> WebSurfaceControls:
        identity = await self.admission.local_user(request)
        api = self.admission.available(self.services)
        controls = await self.authorization_access_control(api).controls(identity.id)
        return WebSurfaceControls(user=WebUserView.from_record(identity), controls=controls)

    async def resolve_access_request(
        self, request_id: UUID, payload: AccessResolvePayload, request: Request
    ) -> ResolvedAccessRequest:
        api = self.admission.mutation(request, self.services)
        identity = await self.admission.local_user(request)
        result = await self.authorization_access_control(api).resolve_request(
            request_id,
            admin_user_id=identity.id,
            approve=payload.approve,
            account_scope=payload.account_scope,
            account_ids=payload.account_ids,
            expires_at=payload.expires_at,
        )
        if api.realtime is not None:
            await api.realtime.publish("access.sessions", "request_resolved", result)
        return result

    async def update_access_session(
        self, session_id: UUID, payload: AccessSessionUpdatePayload, request: Request
    ) -> SessionSnapshot:
        api = self.admission.mutation(request, self.services)
        identity = await self.admission.local_user(request)
        result = await self.authorization_access_control(api).update_session(
            session_id,
            admin_user_id=identity.id,
            access_level=payload.access_level,
            account_scope=payload.account_scope,
            account_ids=payload.account_ids,
            expires_at=payload.expires_at,
            label=payload.label,
        )
        if api.realtime is not None:
            await api.realtime.publish("access.sessions", "session_updated", result)
        return result

    async def revoke_access_session(self, session_id: UUID, request: Request) -> Response:
        api = self.admission.mutation(request, self.services)
        identity = await self.admission.local_user(request)
        await self.authorization_access_control(api).revoke_session(
            session_id, admin_user_id=identity.id
        )
        if api.realtime is not None:
            event = WebSessionRevoked(session_id=session_id)
            await api.realtime.publish("access.sessions", "session_revoked", event)
        return Response(status_code=204)

    async def update_access_controls(
        self, payload: AccessControlBatchPayload, request: Request
    ) -> WebUserControls:
        api = self.admission.mutation(request, self.services)
        identity = await self.admission.local_user(request)
        controls = await self.authorization_access_control(api).set_controls(
            user_id=identity.id,
            items=[(item.surface_id, item.mode) for item in payload.items],
        )
        result = WebUserControls(user=WebUserView.from_record(identity), controls=controls)
        if api.realtime is not None:
            await api.realtime.publish("access.sessions", "controls_changed", result)
        return result
