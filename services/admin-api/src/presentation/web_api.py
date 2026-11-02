"""Compose the retained administration HTTP families without activating a new surface."""

from __future__ import annotations

import asyncio
from typing import Protocol

from application.browser_inputs import BrowserPageSelection
from application.browser_inputs import BrowserThemePayload as BrowserThemePayload
from application.browser_inputs import ViewportPayload as ViewportPayload
from application.frontend_telemetry import FrontendTelemetryBatch as FrontendTelemetryBatch
from application.runtime_settings import PrepareRuntimeSettings, SaveRuntimeSettings
from application.settings_command import SettingsPayload as SettingsPayload
from application.web_accounts import CreateWebAccount, UpdateWebAccount, VerifyWebAccountCandidate
from application.web_session import CurrentWebAdministrator, LoginWebAdministrator
from application.web_session_contracts import LoginRequest as LoginRequest
from application.web_settings import UpdateWebSettings, WebSettingsSnapshotReader
from fastapi import APIRouter
from infrastructure.runtime_settings import (
    LegacyAdminWebEvents,
    LegacyBrowserRuntimeChanges,
    LegacyRuntimeSettingsStore,
    LegacyWebReverseSettings,
)
from infrastructure.web_accounts import LegacyCandidateVerifier
from infrastructure.web_session import LegacyWebCredentials, LegacyWebIdentity

from common.settings import AdminApiSettings
from presentation.web_access import WebAccessController, WebAccessServices
from presentation.web_account_routes import WebAccountController, WebAccountServices
from presentation.web_admission import WebAdmission
from presentation.web_analysis import WebAnalysisController, WebAnalysisServices
from presentation.web_browser import WebBrowserController, WebBrowserServices
from presentation.web_calls import WebCallController
from presentation.web_calls import _decode_call_cursor as _decode_call_cursor
from presentation.web_calls import _encode_call_cursor as _encode_call_cursor
from presentation.web_dashboard import WebDashboardController, WebDashboardServices
from presentation.web_files import WebFileController, WebFileServices
from presentation.web_models import (
    AccessControlBatchPayload as AccessControlBatchPayload,
)
from presentation.web_models import (
    AccessControlItem as AccessControlItem,
)
from presentation.web_models import (
    AccessResolvePayload as AccessResolvePayload,
)
from presentation.web_models import (
    AccessSessionUpdatePayload as AccessSessionUpdatePayload,
)
from presentation.web_models import (
    AccountCandidatePayload as AccountCandidatePayload,
)
from presentation.web_models import (
    AccountPayload as AccountPayload,
)
from presentation.web_models import (
    AccountUpdatePayload as AccountUpdatePayload,
)
from presentation.web_models import (
    ProjectCreatePayload as ProjectCreatePayload,
)
from presentation.web_models import (
    WorkerControlPayload as WorkerControlPayload,
)
from presentation.web_models import (
    WorkerRecoverPayload as WorkerRecoverPayload,
)
from presentation.web_oauth import WebOAuthController
from presentation.web_services import WebApiServices as WebApiServices
from presentation.web_session_routes import WebSessionController
from presentation.web_settings import WebSettingsController, WebSettingsServices
from presentation.web_telemetry import WebTelemetryController, WebTelemetryServices
from presentation.web_terminal import WebTerminalController

BrowserRemoteDebugPayload = BrowserPageSelection


class _WebRouteFamily(Protocol):
    def mount(self, router: APIRouter) -> None: ...


def _settings_services(
    services: WebApiServices | None, lock: asyncio.Lock, events: LegacyAdminWebEvents
) -> WebSettingsServices | None:
    if services is None:
        return None
    store = LegacyRuntimeSettingsStore(services.config, services.runtime_settings)
    reverse = LegacyWebReverseSettings(services.reverse)
    reader = WebSettingsSnapshotReader(store, reverse)
    update = UpdateWebSettings(
        reader,
        PrepareRuntimeSettings(store),
        SaveRuntimeSettings(store, LegacyBrowserRuntimeChanges(services.web, services.realtime)),
        reverse,
        events,
        lock,
    )
    return WebSettingsServices(audit=services.audit, reader=reader, update=update)


class AdminWebController:
    """One router lifetime for focused HTTP families and their shared admission state."""

    def __init__(self, settings: AdminApiSettings, services: WebApiServices | None) -> None:
        self.router = APIRouter(prefix="/v1", tags=["admin"])
        identity = (
            LegacyWebIdentity(services.authorization_identity)
            if services is not None and services.authorization_identity
            else None
        )
        admission = WebAdmission(
            settings, CurrentWebAdministrator(identity), services_available=services is not None
        )
        events = LegacyAdminWebEvents(services.realtime if services is not None else None)
        candidate_slots = asyncio.Semaphore(4)
        settings_lock = asyncio.Lock()
        families: tuple[_WebRouteFamily, ...] = (
            WebSessionController(
                admission,
                None
                if services is None
                else LoginWebAdministrator(
                    identity,
                    LegacyWebCredentials(
                        settings.legacy_admin_username, settings.legacy_admin_password
                    ),
                    remote_authority=bool(settings.authorization_admin_service_token),
                ),
            ),
            WebAccessController(
                admission,
                None
                if services is None
                else WebAccessServices(
                    realtime=services.realtime, authorization_access=services.authorization_access
                ),
            ),
            WebDashboardController(
                admission,
                None
                if services is None
                else WebDashboardServices(
                    accounts=services.accounts,
                    audit=services.audit,
                    oauth_sessions=services.oauth_sessions,
                    snapshots=services.snapshots,
                ),
            ),
            WebAccountController(
                admission,
                None
                if services is None
                else WebAccountServices(
                    accounts=services.accounts,
                    create=CreateWebAccount(services.accounts),
                    update=UpdateWebAccount(services.accounts),
                    candidate=VerifyWebAccountCandidate(
                        services.accounts,
                        LegacyCandidateVerifier(services.accounts),
                        candidate_slots,
                    ),
                ),
            ),
            WebCallController(
                admission,
                None if services is None else services.audit,
                events,
            ),
            WebOAuthController(
                admission,
                None if services is None else services.oauth_sessions,
            ),
            WebFileController(
                admission,
                None
                if services is None
                else WebFileServices(snapshots=services.snapshots, files=services.files),
                events,
            ),
            WebTerminalController(
                admission,
                None if services is None else services.terminal,
                events,
            ),
            WebAnalysisController(
                admission,
                None
                if services is None
                else WebAnalysisServices(
                    snapshots=services.snapshots,
                    reverse=services.reverse,
                    snapshot_refresher=services.snapshot_refresher,
                ),
                events,
            ),
            WebBrowserController(
                admission,
                None
                if services is None
                else WebBrowserServices(web=services.web, realtime=services.realtime),
            ),
            WebTelemetryController(
                admission,
                None if services is None else WebTelemetryServices(telemetry=services.telemetry),
            ),
            WebSettingsController(
                admission, _settings_services(services, settings_lock, events), events
            ),
        )
        for family in families:
            family.mount(self.router)


def build_admin_api_router(
    settings: AdminApiSettings, services: WebApiServices | None = None
) -> APIRouter:
    return AdminWebController(settings, services).router
