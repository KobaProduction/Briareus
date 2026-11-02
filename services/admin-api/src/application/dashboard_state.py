"""Aggregate existing read services into the unchanged dashboard response."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING, Self

from domain.accounts import Provider
from domain.telemetry import InvocationSummary
from pydantic import BaseModel

from common.account_contracts import AccountPublic

from .analysis_views import AnalysisOverview
from .snapshot_views import (
    REVERSE_OVERVIEW_KEY,
    WORKSPACE_STATS_KEY,
    MissingSnapshotPayload,
    SnapshotMetadataView,
    snapshot_meta,
)
from .workspace_views import FileWorkspaceStats

if TYPE_CHECKING:
    from .services import (
        AccountService,
        InvocationAuditService,
        OAuthSessionService,
        SnapshotService,
    )


class DashboardAccounts(BaseModel):
    total: int
    enabled: int
    by_provider: dict[str, int]

    @classmethod
    def from_accounts(cls, accounts: Sequence[AccountPublic]) -> Self:
        return cls(
            total=len(accounts),
            enabled=sum(1 for item in accounts if item.enabled),
            by_provider={
                provider.value: sum(
                    1 for item in accounts if item.provider == provider.value and item.enabled
                )
                for provider in Provider
            },
        )


class DashboardOAuth(BaseModel):
    tracked: int
    active: int


class DashboardAnalysis(BaseModel):
    projects: int
    active_sessions: int
    workers: int
    running_workers: int

    @classmethod
    def from_overview(cls, overview: AnalysisOverview | None) -> Self:
        projects = overview.projects if overview else []
        workers = overview.workers if overview else []
        return cls(
            projects=len(projects),
            active_sessions=sum(item.session == "active" for item in projects),
            workers=len(workers),
            running_workers=sum(item.running for item in workers),
        )


class DashboardState(BaseModel):
    accounts: DashboardAccounts
    calls: InvocationSummary
    oauth: DashboardOAuth
    workspace: FileWorkspaceStats | MissingSnapshotPayload
    workspace_meta: SnapshotMetadataView
    analysis: DashboardAnalysis
    analysis_meta: SnapshotMetadataView


async def build_dashboard_state(
    accounts_service: AccountService,
    audit: InvocationAuditService,
    oauth_sessions: OAuthSessionService,
    snapshots: SnapshotService,
) -> DashboardState:
    accounts, calls, oauth, workspace, reverse_snapshot = await asyncio.gather(
        accounts_service.list(),
        audit.summary(),
        oauth_sessions.recent(limit=1000),
        snapshots.get(WORKSPACE_STATS_KEY),
        snapshots.get(REVERSE_OVERVIEW_KEY),
    )
    return DashboardState(
        accounts=DashboardAccounts.from_accounts(accounts),
        calls=calls,
        oauth=DashboardOAuth(
            tracked=len(oauth), active=sum(1 for item in oauth if item.status == "active")
        ),
        workspace=workspace.content
        if workspace is not None and isinstance(workspace.content, FileWorkspaceStats)
        else MissingSnapshotPayload(),
        workspace_meta=snapshot_meta(workspace),
        analysis=DashboardAnalysis.from_overview(
            reverse_snapshot.content
            if reverse_snapshot is not None
            and isinstance(reverse_snapshot.content, AnalysisOverview)
            else None
        ),
        analysis_meta=snapshot_meta(reverse_snapshot),
    )
