from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from auth_service.provider import MultiResourceZitadelProvider
from briareus_cache.cache import SharedCache
from briareus_cache.settings import ValkeySettings
from briareus_control_panel_client.control_panel_client import ControlPanelClient
from briareus_control_panel_client.settings import ControlPanelClientSettings
from briareus_identity.identity_provider import ZitadelClient
from briareus_identity.identity_settings import (
    McpAuthSettings,
    PanelIdentitySettings,
    ZitadelSettings,
)
from briareus_telemetry.observability import announce_runtime_started, build_observability
from briareus_workspace.settings import FileSettings
from fastapi import FastAPI
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware

from control_panel_api.api_errors import install_admin_api_error_handlers
from control_panel_api.application.identity import PanelIdentityService
from control_panel_api.application.services import (
    AccountService,
    ControlPanelConfigService,
    InvocationAuditService,
    OAuthSessionService,
    RuntimeSettingsService,
    SnapshotService,
)
from control_panel_api.browser_api import build_browser_operator_api_router
from control_panel_api.dashboard_state import build_dashboard_state
from control_panel_api.infrastructure.crypto import FernetCredentialCipher
from control_panel_api.infrastructure.database import create_database
from control_panel_api.infrastructure.files import FileAdminStore
from control_panel_api.infrastructure.identity_provider import ZitadelPanelIdentity
from control_panel_api.infrastructure.identity_sessions import SqlIdentitySessionRepository
from control_panel_api.infrastructure.migrations import run_migrations
from control_panel_api.infrastructure.provider_checks import ProviderConnectionVerifier
from control_panel_api.infrastructure.repositories import (
    SqlAlchemyAccountRepository,
    SqlAlchemyControlPanelConfigRepository,
    SqlAlchemyInvocationRepository,
    SqlAlchemyOAuthSessionRepository,
    SqlAlchemyRuntimeSettingsRepository,
    SqlAlchemySnapshotRepository,
)
from control_panel_api.infrastructure.reverse import ReverseAdminClient
from control_panel_api.infrastructure.snapshot_worker import SnapshotRefresher
from control_panel_api.infrastructure.terminal import TerminalAdminClient
from control_panel_api.infrastructure.web import WebAdminClient
from control_panel_api.oauth_host import install_mcp_oauth
from control_panel_api.presentation.api import ApiServices, build_internal_router
from control_panel_api.presentation.identity import build_identity_router
from control_panel_api.presentation.web_api import WebApiServices, build_admin_api_router
from control_panel_api.realtime import RealtimeBus
from control_panel_api.realtime_api import build_realtime_router
from control_panel_api.settings import ControlPanelSettings
from control_panel_api.telemetry_ingest import FrontendTelemetryProxy, TelemetryUpstream

logger = logging.getLogger(__name__)

settings = ControlPanelSettings()
settings.validate_bootstrap()
_observability = build_observability("control-panel-api")
announce_runtime_started(_observability, "control-panel-api")
engine, sessions = create_database(settings.database_url)
run_migrations(engine)

cache_settings = ValkeySettings()
shared_cache = SharedCache(cache_settings)
realtime = RealtimeBus(shared_cache, cache_settings)
telemetry = FrontendTelemetryProxy(
    TelemetryUpstream(
        url=settings.frontend_telemetry_upstream_url,
        bearer_token=settings.frontend_telemetry_bearer_token,
    )
)
cipher = FernetCredentialCipher(settings.encryption_key)
identity_settings = ZitadelSettings()
identity_client = ZitadelClient(identity_settings)
identity_client.metadata()
public_origin = PanelIdentitySettings().public_origin
identity = PanelIdentityService(
    SqlIdentitySessionRepository(engine, cipher),
    ZitadelPanelIdentity(identity_client, public_origin),
    issuer=identity_settings.canonical_issuer,
    allowed_subjects=identity_settings.allowed_subjects,
)
account_repository = SqlAlchemyAccountRepository(sessions)
invocation_repository = SqlAlchemyInvocationRepository(sessions)
config_repository = SqlAlchemyControlPanelConfigRepository(sessions)
runtime_settings_repository = SqlAlchemyRuntimeSettingsRepository(sessions)
oauth_session_repository = SqlAlchemyOAuthSessionRepository(sessions)
snapshot_repository = SqlAlchemySnapshotRepository(sessions)
config_service = ControlPanelConfigService(
    config_repository, cache=shared_cache, cache_settings=cache_settings
)
runtime_settings = RuntimeSettingsService(
    runtime_settings_repository,
    cipher=cipher,
    cache=shared_cache,
    cache_settings=cache_settings,
)
oauth_sessions = OAuthSessionService(oauth_session_repository)
snapshots = SnapshotService(snapshot_repository)
config_service.get()
accounts = AccountService(
    account_repository,
    cipher,
    ProviderConnectionVerifier(),
    cache=shared_cache,
    cache_settings=cache_settings,
    publisher=realtime.publish_sync,
)
audit = InvocationAuditService(
    invocation_repository, config_service, publisher=realtime.publish_sync
)
files = FileAdminStore(FileSettings())
reverse = ReverseAdminClient()
snapshot_refresher = SnapshotRefresher(snapshots, files, reverse)
terminal = TerminalAdminClient()
web_admin = WebAdminClient()


async def _realtime_state_loop() -> None:
    while True:
        try:
            dashboard_state = await build_dashboard_state(
                accounts, audit, oauth_sessions, snapshots
            )
            await realtime.publish("system.metrics", "snapshot", dashboard_state)
            try:
                browser_state = await web_admin.status()
            except Exception as exc:
                browser_state = {"available": False, "error": str(exc)}
            await realtime.publish("browser.runtime", "state", browser_state)
        except Exception:
            logger.exception("Control Panel realtime state refresh failed")
        await asyncio.sleep(10)


async def _maintenance_loop() -> None:
    interval_seconds = 3600
    while True:
        try:
            config = await asyncio.to_thread(config_service.get)
            interval_seconds = config.maintenance_interval_minutes * 60
            logger.info(
                "Control Panel cleanup scan started retention_days=%d "
                "max_records=%d interval_minutes=%d",
                config.logging_retention_days,
                config.logging_max_records,
                config.maintenance_interval_minutes,
            )
            removed = await asyncio.to_thread(audit.cleanup)
            logger.info(
                "Control Panel cleanup scan completed reason=retention_or_max_records "
                "removed_records=%d",
                removed,
            )
        except Exception:
            logger.exception("Control Panel maintenance cycle failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    realtime.start()
    telemetry.start()
    await snapshot_refresher.ensure_base_snapshots()
    tasks = [
        asyncio.create_task(_realtime_state_loop(), name="management-realtime-state"),
        asyncio.create_task(_maintenance_loop(), name="management-maintenance"),
        # Disable automatic full-workspace traversal: millions of inodes
        # on the shared volume can trigger host-wide memory pressure.
        asyncio.create_task(
            snapshot_refresher.reverse_loop(),
            name="management-reverse-snapshots",
        ),
        asyncio.create_task(
            snapshot_refresher.coverage_loop(),
            name="management-coverage-snapshots",
        ),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await telemetry.close()
        await realtime.close()


app = FastAPI(
    title="Briareus Control Panel API",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
    middleware=[
        Middleware(
            SessionMiddleware,
            secret_key=settings.session_secret,
            https_only=settings.session_https_only,
            same_site="lax",
        )
    ],
)


install_admin_api_error_handlers(app)

app.include_router(build_identity_router(identity, public_origin))

app.include_router(
    build_internal_router(
        ApiServices(
            accounts=accounts,
            audit=audit,
            oauth_sessions=oauth_sessions,
            runtime_settings=runtime_settings,
            service_token=settings.service_token,
        )
    )
)
app.include_router(
    build_admin_api_router(
        settings,
        WebApiServices(
            accounts=accounts,
            audit=audit,
            oauth_sessions=oauth_sessions,
            snapshots=snapshots,
            config=config_service,
            runtime_settings=runtime_settings,
            files=files,
            reverse=reverse,
            terminal=terminal,
            web=web_admin,
            snapshot_refresher=snapshot_refresher,
            realtime=realtime,
            telemetry=telemetry,
        ),
        identity=identity,
        public_origin=public_origin,
    )
)
app.include_router(
    build_realtime_router(
        realtime,
        accounts,
        audit,
        oauth_sessions,
        snapshots,
        web_admin,
        identity=identity,
        public_origin=public_origin,
    )
)
app.include_router(
    build_browser_operator_api_router(settings, identity=identity, public_origin=public_origin)
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


oauth_settings = McpAuthSettings()
oauth_settings.validate_bootstrap()
oauth_provider = MultiResourceZitadelProvider(
    oauth_settings,
    identity_client,
    ControlPanelClient(ControlPanelClientSettings()),
)
install_mcp_oauth(app, oauth_provider)
