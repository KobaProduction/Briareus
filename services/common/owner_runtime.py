"""Private owner HTTP boundary and owner-scoped startup composition."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import partial
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from starlette.responses import Response

from common.application.owner_ingress import AttestOwnerIngress, OwnerIngressVerifier
from common.application.owner_startup import OwnerNotReady, OwnerRuntimeStatus, OwnerStartup
from common.domain.owner_runtime import VerifiedOwnerIngress, permits_local_schema_status
from common.infrastructure.owner_startup import SqlOwnerSchemaLifecycle
from common.owner_startup_diagnostics import safe_owner_startup_diagnostic
from common.platform_db import OWNER_DB_NAMES, OwnerDatabaseSettings, OwnerName

__all__ = ["OwnerIngressVerifier", "OwnerReadiness", "VerifiedOwnerIngress", "create_owner_app"]
logger = logging.getLogger(__name__)
_FORWARDED = frozenset(
    {"forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip"}
)


class OwnerLiveness(BaseModel):
    owner: str
    state: str = "live"


class OwnerReadiness(BaseModel):
    owner: str
    state: str = "not_started"
    revision: str | None = None
    table_count: int = 0
    security_ready: bool = False


def _readiness(status: OwnerRuntimeStatus) -> OwnerReadiness:
    return OwnerReadiness(
        owner=status.owner,
        state=status.state,
        revision=status.revision,
        table_count=status.table_count,
        security_ready=status.security_ready,
    )


_utc_now = partial(datetime.now, UTC)


class OwnerHttpBoundary:
    def __init__(self, startup: OwnerStartup, resources: SqlOwnerSchemaLifecycle) -> None:
        self.startup = startup
        self.resources = resources

    @asynccontextmanager
    async def lifespan(self, _app: FastAPI) -> AsyncIterator[None]:
        try:
            await self.startup.start()
            logger.info(
                "owner schema verified owner=%s head=%s",
                self.startup.owner,
                self.startup.status.revision,
            )
            yield
        except Exception as error:
            self.startup.failed()
            self._report_failure(error)
        finally:
            await self.startup.close()

    def _report_failure(self, error: Exception) -> None:
        reason = safe_owner_startup_diagnostic(phase=self.startup.phase, error=error)
        owner = self.startup.owner
        telemetry = self.resources.telemetry
        environment = telemetry.settings.environment if telemetry is not None else "unconfigured"
        # Only fixed allowlisted diagnostic fields; never exception text or DSNs.
        logger.error(
            "owner_startup_failure owner=%s db=%s phase=%s "
            "category=%s exception=%s sqlstate=%s service.name=%s deployment.environment=%s",
            owner,
            OWNER_DB_NAMES[owner],
            reason.phase,
            reason.reason,
            reason.exception_type,
            reason.sqlstate or "none",
            "authorization" if owner == "access" else owner,
            environment,
        )
        raise RuntimeError(
            f"owner startup unavailable owner={owner} phase={reason.phase} "
            f"reason={reason.reason} sqlstate={reason.sqlstate or 'none'}"
        ) from None

    async def telemetry(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = perf_counter()
        active = self.resources.telemetry
        status = 500
        try:
            if active is None:
                response = await call_next(request)
            else:
                with active.trace_request(method=request.method, correlation_id=str(uuid4())):
                    response = await call_next(request)
            status = response.status_code
            return response
        finally:
            if active is not None:
                active.observe_http(
                    method=request.method,
                    status_code=status,
                    duration_ms=(perf_counter() - started) * 1000,
                )

    async def live(self) -> OwnerLiveness:
        return OwnerLiveness(owner=self.startup.owner)

    async def ready(self) -> OwnerReadiness:
        try:
            return _readiness(await self.startup.require_ready())
        except OwnerNotReady as error:
            raise HTTPException(503, detail=str(error)) from None

    async def schema_status(self, request: Request) -> OwnerReadiness:
        bound = request.scope.get("server")
        server_host = (
            bound[0]
            if isinstance(bound, (tuple, list)) and bound and isinstance(bound[0], str)
            else ""
        )
        if not permits_local_schema_status(
            origin=request.client.host if request.client is not None else "",
            server_host=server_host,
            forwarded=any(key in request.headers for key in _FORWARDED),
        ):
            raise HTTPException(404, detail="not found")
        return _readiness(self.startup.status)


def create_owner_app(
    owner: OwnerName,
    *,
    settings: OwnerDatabaseSettings | None = None,
    trusted_ingress: OwnerIngressVerifier | None = None,
) -> FastAPI:
    resources = SqlOwnerSchemaLifecycle(owner, settings)
    startup = OwnerStartup(owner, resources, AttestOwnerIngress(owner, trusted_ingress, _utc_now))
    boundary = OwnerHttpBoundary(startup, resources)
    app = FastAPI(
        title=f"Briareus {owner} private owner",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=boundary.lifespan,
    )
    app.middleware("http")(boundary.telemetry)
    app.add_api_route("/health/live", boundary.live, methods=["GET"], include_in_schema=False)
    app.add_api_route("/health/ready", boundary.ready, methods=["GET"], include_in_schema=False)
    app.add_api_route(
        "/internal/schema-status", boundary.schema_status, methods=["GET"], include_in_schema=False
    )
    return app
