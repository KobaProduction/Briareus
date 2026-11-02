"""HTTP adapters for the approval application boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from control_panel_api._api_paths import API_V1_PREFIX
from control_panel_api._oidc_membership import CurrentPlatformContext
from control_panel_api._oidc_origin_policy import BROWSER_ORIGIN, local_browser_host
from control_panel_api.application.approval_contracts import (
    ActorBoundApprovalSource,
    ApprovalManagementPort,
    ApprovalSnapshot,
    ApprovalSource,
    CurrentSessionSnapshot,
    OwnerManagementUnavailable,
)
from control_panel_api.application.approval_execution import ApprovalFailure, ApprovalFailureCode
from control_panel_api.application.approval_management import (
    ApprovalActor,
    ApprovalManagement,
    ElevationCommand,
    ResolutionCommand,
)
from control_panel_api.application.approval_receipts import approval_lifecycle
from control_panel_api.application.approval_scopes import ScopedEffectPayload
from control_panel_api.domain.approval_policy import resolution_actions
from control_panel_api.domain.platform_authority import ResolvedPlatformUser

from .approval_models import (
    ApprovalResponse,
    OpenSessionRequest,
    RequestElevation,
    ResolveElevation,
    RevokeSession,
    SessionResponse,
)

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@dataclass(slots=True)
class ApprovalController:
    current_context: CurrentPlatformContext
    owner: ApprovalSource | None
    expected_origin: str
    expected_host: str | None

    def fail(self, status: int, code: str) -> JSONResponse:
        return JSONResponse(
            status_code=status, content={"error": {"code": code}}, headers=_NO_STORE
        )

    def project_access(
        self, proof: ResolvedPlatformUser, project_uuid: UUID, *, approve: bool
    ) -> bool:
        for item in proof.projects:
            if item.project_uuid == project_uuid:
                return (
                    "approve_agent_session" in item.permissions
                    if approve
                    else "use_resources" in item.permissions
                )
        return False

    async def verified(
        self, request: Request, project_uuid: UUID
    ) -> ResolvedPlatformUser | JSONResponse:
        current = await self.current_context(request, project_uuid)
        if isinstance(current, JSONResponse):
            return current
        session, proof = current
        return replace(proof, expires_at=min(proof.expires_at, session.expires_at))

    def scoped_owner(self, proof: ResolvedPlatformUser) -> ApprovalManagementPort:
        if self.owner is None:
            raise OwnerManagementUnavailable("Access owner not configured")
        if isinstance(self.owner, ActorBoundApprovalSource):
            return self.owner.for_actor(proof)
        return self.owner

    def mutate(self, request: Request) -> UUID | JSONResponse:
        if (
            request.headers.getlist("origin") != [self.expected_origin]
            or (
                self.expected_host is not None
                and request.headers.getlist("host") != [self.expected_host]
            )
            or request.headers.getlist("content-type") != ["application/json"]
        ):
            return self.fail(403, "APPROVAL_ORIGIN_REQUIRED")
        operation_headers = request.headers.getlist("operation-uuid")
        idempotency_headers = request.headers.getlist("idempotency-key")
        if len(operation_headers) != 1 or idempotency_headers != operation_headers:
            return self.fail(422, "APPROVAL_OPERATION_ID_REQUIRED")
        try:
            operation = UUID(operation_headers[0])
        except (ValueError, AttributeError):
            return self.fail(422, "APPROVAL_OPERATION_ID_INVALID")
        if operation.version != 4 or str(operation) != operation_headers[0]:
            return self.fail(422, "APPROVAL_OPERATION_ID_INVALID")
        return operation

    def snapshot(self, item: ApprovalSnapshot, actor: UUID, *, approver: bool) -> ApprovalResponse:
        return ApprovalResponse(
            id=str(item.approval_uuid),
            project_uuid=str(item.project_uuid),
            agent_session_uuid=str(item.agent_session_uuid),
            requested_by_user_uuid=str(item.requested_by_user_uuid),
            label=item.label,
            created_at=item.created_at.isoformat() if item.created_at else None,
            status=item.status,
            version=item.version,
            requested_operations=list(item.requested_operations),
            requested_resources=[
                ScopedEffectPayload.from_scope(scope) for scope in item.requested_resources
            ],
            requested_expires_at=item.requested_expires_at.isoformat(),
            resolved_by_user_uuid=str(item.resolved_by_user_uuid)
            if item.resolved_by_user_uuid
            else None,
            issued_session_uuid=str(item.issued_session_uuid) if item.issued_session_uuid else None,
            allowed_actions=list(
                resolution_actions(
                    approval_lifecycle(item),
                    actor=actor,
                    approver=approver,
                    expires_at=item.requested_expires_at,
                    now=datetime.now(UTC),
                )
            ),
        )

    async def list_pending(self, request: Request, project_uuid: UUID) -> JSONResponse:
        proof = await self.readable(request, project_uuid)
        if isinstance(proof, JSONResponse):
            return proof
        service = self.service(proof, project_uuid)
        if isinstance(service, JSONResponse):
            return service
        result = await service.list_approvals()
        if isinstance(result, ApprovalFailure):
            return self.failure(result)
        approver = self.project_access(proof, project_uuid, approve=True)
        return JSONResponse(
            {
                "items": [
                    self.snapshot(item, proof.user_uuid, approver=approver).model_dump(mode="json")
                    for item in result
                ]
            },
            headers=_NO_STORE,
        )

    async def current_sessions(self, request: Request, project_uuid: UUID) -> JSONResponse:
        proof = await self.readable(request, project_uuid)
        if isinstance(proof, JSONResponse):
            return proof
        service = self.service(proof, project_uuid)
        if isinstance(service, JSONResponse):
            return service
        result = await service.list_sessions()
        if isinstance(result, ApprovalFailure):
            return self.failure(result)
        return JSONResponse(
            {"items": [self.session_response(item).model_dump(mode="json") for item in result]},
            headers=_NO_STORE,
        )

    async def current_session(
        self, request: Request, session_uuid: UUID, project_uuid: UUID
    ) -> JSONResponse:
        proof = await self.readable(request, project_uuid)
        if isinstance(proof, JSONResponse):
            return proof
        if session_uuid.version != 4:
            return self.fail(422, "AGENT_SESSION_INVALID")
        service = self.service(proof, project_uuid)
        if isinstance(service, JSONResponse):
            return service
        result = await service.get_session(session_uuid)
        if isinstance(result, ApprovalFailure):
            return self.failure(result)
        return JSONResponse(
            self.session_response(result).model_dump(mode="json"), headers=_NO_STORE
        )

    async def require_write(
        self, request: Request, project_uuid: UUID, *, approve: bool
    ) -> tuple[ResolvedPlatformUser, UUID] | JSONResponse:
        proof = await self.verified(request, project_uuid)
        if isinstance(proof, JSONResponse):
            return proof
        if project_uuid.version != 4 or not self.project_access(
            proof, project_uuid, approve=approve
        ):
            return self.fail(403, "PROJECT_PERMISSION_DENIED")
        operation = self.mutate(request)
        if isinstance(operation, JSONResponse):
            return operation
        if self.owner is None:
            return self.fail(503, "APPROVAL_OWNER_UNAVAILABLE")
        return (proof, operation)

    async def open_session(self, request: Request, body: OpenSessionRequest) -> JSONResponse:
        authorized = await self.require_write(request, body.project_uuid, approve=False)
        if isinstance(authorized, JSONResponse):
            return authorized
        proof, operation = authorized
        service = self.service(proof, body.project_uuid)
        if isinstance(service, JSONResponse):
            return service
        result = await service.open_session(
            elevation_policy=body.elevation_policy, label=body.label, operation=operation
        )
        if isinstance(result, ApprovalFailure):
            return self.failure(result)
        return JSONResponse(
            {
                "session_uuid": str(result.session_uuid),
                "project_uuid": str(result.project_uuid),
                "revision": result.revision,
                "status": result.status,
                "is_elevated": False,
                "elevation_policy": result.elevation_policy,
                "hard_expires_at": result.hard_expires_at.isoformat(),
                "operations": list(result.operations),
                "resources": [],
            },
            status_code=201,
            headers=_NO_STORE,
        )

    async def request_elevation(self, request: Request, body: RequestElevation) -> JSONResponse:
        authorized = await self.require_write(request, body.project_uuid, approve=False)
        if isinstance(authorized, JSONResponse):
            return authorized
        proof, operation = authorized
        service = self.service(proof, body.project_uuid)
        if isinstance(service, JSONResponse):
            return service
        command = ElevationCommand(
            body.agent_session_uuid,
            body.operations,
            tuple(item.scope() for item in body.resources),
            body.seconds,
            body.expected_grant_revision,
            operation,
        )
        result = await service.request_elevation(command)
        if isinstance(result, ApprovalFailure):
            return self.failure(result)
        return JSONResponse(
            self.snapshot(result, proof.user_uuid, approver=False).model_dump(mode="json"),
            status_code=202,
            headers=_NO_STORE,
        )

    async def resolve_elevation(
        self, request: Request, approval_uuid: UUID, body: ResolveElevation
    ) -> JSONResponse:
        authorized = await self.require_write(request, body.project_uuid, approve=True)
        if isinstance(authorized, JSONResponse):
            return authorized
        proof, operation = authorized
        service = self.service(proof, body.project_uuid)
        if isinstance(service, JSONResponse):
            return service
        command = ResolutionCommand(
            approval_uuid,
            body.expected_approval_version,
            body.approve,
            body.allowed_operations,
            operation,
        )
        result = await service.resolve_elevation(command)
        if isinstance(result, ApprovalFailure):
            return self.failure(result)
        return JSONResponse(
            self.snapshot(result, proof.user_uuid, approver=True).model_dump(mode="json"),
            headers=_NO_STORE,
        )

    async def revoke_session(
        self, request: Request, session_uuid: UUID, body: RevokeSession
    ) -> JSONResponse:
        authorized = await self.require_write(request, body.project_uuid, approve=True)
        if isinstance(authorized, JSONResponse):
            return authorized
        proof, operation = authorized
        service = self.service(proof, body.project_uuid)
        if isinstance(service, JSONResponse):
            return service
        result = await service.revoke_session(
            session=session_uuid,
            expected_revision=body.expected_grant_revision,
            operation=operation,
        )
        if isinstance(result, ApprovalFailure):
            return self.failure(result)
        return JSONResponse(
            {
                "session_uuid": str(result.session_uuid),
                "project_uuid": str(result.project_uuid),
                "status": "revoked",
                "revision": result.revision,
            },
            headers=_NO_STORE,
        )

    def session_response(self, item: CurrentSessionSnapshot) -> SessionResponse:
        return SessionResponse(
            session_uuid=str(item.session_uuid),
            project_uuid=str(item.project_uuid),
            created_by_user_uuid=str(item.created_by_user_uuid),
            label=item.label,
            created_at=item.created_at.isoformat() if item.created_at else None,
            revision=item.revision,
            status=item.status,
            is_elevated=item.is_elevated,
            elevation_policy=item.elevation_policy,
            hard_expires_at=item.hard_expires_at.isoformat(),
            operations=list(item.operations),
            resources=[ScopedEffectPayload.from_scope(scope) for scope in item.resources],
            allowed_actions=list(item.allowed_actions),
        )

    def service(
        self, proof: ResolvedPlatformUser, project: UUID
    ) -> ApprovalManagement | JSONResponse:
        if self.owner is None:
            return self.fail(503, "APPROVAL_OWNER_UNAVAILABLE")
        actor = ApprovalActor(
            proof.user_uuid,
            project,
            self.project_access(proof, project, approve=True),
            proof.expires_at,
        )
        return ApprovalManagement(self.scoped_owner(proof), actor)

    def failure(self, failure: ApprovalFailure) -> JSONResponse:
        statuses = {
            ApprovalFailureCode.DENIED: 403,
            ApprovalFailureCode.NOT_FOUND: 404,
            ApprovalFailureCode.CONFLICT: 409,
            ApprovalFailureCode.INVALID_SCOPE: 422,
            ApprovalFailureCode.INVALID_SESSION: 422,
            ApprovalFailureCode.INVALID_LABEL: 422,
        }
        return self.fail(statuses.get(failure.code, 503), failure.code.value)

    async def readable(
        self, request: Request, project: UUID
    ) -> ResolvedPlatformUser | JSONResponse:
        proof = await self.verified(request, project)
        if isinstance(proof, JSONResponse):
            return proof
        if project.version != 4 or not (
            self.project_access(proof, project, approve=False)
            or self.project_access(proof, project, approve=True)
        ):
            return self.fail(403, "PROJECT_ACCESS_DENIED")
        return proof


def approval_management_router(
    *,
    current_context: CurrentPlatformContext,
    owner: ApprovalSource | None,
    test_only_local_origin: str | None = None,
) -> APIRouter:
    controller = ApprovalController(
        current_context,
        owner,
        test_only_local_origin or BROWSER_ORIGIN,
        local_browser_host(test_only_local_origin),
    )
    router = APIRouter()
    router.get(API_V1_PREFIX + "/approvals")(controller.list_pending)
    router.get(API_V1_PREFIX + "/agent-sessions")(controller.current_sessions)
    router.get(API_V1_PREFIX + "/agent-sessions/{session_uuid}")(controller.current_session)
    router.post(API_V1_PREFIX + "/agent-sessions")(controller.open_session)
    router.post(API_V1_PREFIX + "/approvals")(controller.request_elevation)
    router.post(API_V1_PREFIX + "/approvals/{approval_uuid}/resolve")(controller.resolve_elevation)
    router.post(API_V1_PREFIX + "/agent-sessions/{session_uuid}/revoke")(controller.revoke_session)
    return router
