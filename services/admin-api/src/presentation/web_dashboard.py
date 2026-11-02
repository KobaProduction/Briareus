"""Retained dashboard HTTP adapters with focused dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from application.dashboard_state import DashboardState
from application.services import (
    AccountService,
    InvocationAuditService,
    OAuthSessionService,
    SnapshotService,
)
from dashboard_state import build_dashboard_state
from fastapi import APIRouter, Request

from presentation.web_admission import WebAdmission


@dataclass(frozen=True, slots=True)
class WebDashboardServices:
    accounts: AccountService
    audit: InvocationAuditService
    oauth_sessions: OAuthSessionService
    snapshots: SnapshotService


@dataclass(eq=False, repr=False)
class WebDashboardController:
    admission: WebAdmission
    services: WebDashboardServices | None

    def mount(self, router: APIRouter) -> None:
        router.get("/dashboard")(self.dashboard)

    async def dashboard(self, request: Request) -> DashboardState:
        self.admission.require_user(request)
        api = self.admission.available(self.services)
        return await build_dashboard_state(
            api.accounts, api.audit, api.oauth_sessions, api.snapshots
        )
