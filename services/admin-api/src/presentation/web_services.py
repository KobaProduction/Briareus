"""Compatibility composition inputs for the retained administration surface."""

from __future__ import annotations

from dataclasses import dataclass

from application.services import (
    AccountService,
    AdminConfigService,
    InvocationAuditService,
    OAuthSessionService,
    RuntimeSettingsService,
    SnapshotService,
)
from infrastructure.authorization_access import AuthorizationAccessAdminClient
from infrastructure.authorization_identity import AuthorizationIdentityClient
from infrastructure.files import FileAdminStore
from infrastructure.reverse import ReverseAdminClient
from infrastructure.snapshot_worker import (
    SnapshotRefresher,
)
from infrastructure.terminal import TerminalAdminClient
from infrastructure.web import WebAdminClient
from realtime import RealtimeBus
from telemetry_ingest import FrontendTelemetryProxy


@dataclass(frozen=True)
class WebApiServices:
    accounts: AccountService
    audit: InvocationAuditService
    oauth_sessions: OAuthSessionService
    snapshots: SnapshotService
    config: AdminConfigService
    runtime_settings: RuntimeSettingsService
    files: FileAdminStore
    reverse: ReverseAdminClient
    terminal: TerminalAdminClient
    web: WebAdminClient
    snapshot_refresher: SnapshotRefresher
    realtime: RealtimeBus | None = None
    telemetry: FrontendTelemetryProxy | None = None
    authorization_access: AuthorizationAccessAdminClient | None = None
    authorization_identity: AuthorizationIdentityClient | None = None
