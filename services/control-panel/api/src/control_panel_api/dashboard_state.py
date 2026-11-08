from __future__ import annotations

import asyncio
from collections.abc import Sequence

from briareus_account_contracts import AccountPublic

from control_panel_api.application.services import (
    AccountService,
    InvocationAuditService,
    SnapshotService,
)
from control_panel_api.domain.accounts import Provider
from control_panel_api.domain.admin_data import AnalysisOverview, FileStats
from control_panel_api.domain.dashboard import (
    AccountSummary,
    AnalysisSummary,
    DashboardState,
    EmptyData,
)
from control_panel_api.infrastructure.snapshot_worker import (
    REVERSE_OVERVIEW_KEY,
    WORKSPACE_STATS_KEY,
    snapshot_meta,
)


def _account_summary(accounts: Sequence[AccountPublic]) -> AccountSummary:
    return AccountSummary(
        total=len(accounts),
        enabled=sum(item.enabled for item in accounts),
        by_provider={
            provider.value: sum(
                item.provider == provider.value and item.enabled for item in accounts
            )
            for provider in Provider
        },
    )


async def build_dashboard_state(
    accounts_service: AccountService, audit: InvocationAuditService, snapshots: SnapshotService
) -> DashboardState:
    accounts, calls, workspace, reverse_snapshot = await asyncio.gather(
        asyncio.to_thread(accounts_service.list),
        asyncio.to_thread(audit.summary),
        asyncio.to_thread(snapshots.get, WORKSPACE_STATS_KEY),
        asyncio.to_thread(snapshots.get, REVERSE_OVERVIEW_KEY),
    )
    reverse_payload = reverse_snapshot.payload if reverse_snapshot is not None else None
    workspace_payload = workspace.payload if workspace is not None else None
    if reverse_payload is not None and not isinstance(reverse_payload, AnalysisOverview):
        raise TypeError("analysis snapshot has incompatible payload")
    if workspace_payload is not None and not isinstance(workspace_payload, FileStats):
        raise TypeError("workspace snapshot has incompatible payload")
    return DashboardState(
        accounts=_account_summary(accounts),
        calls=calls,
        workspace=workspace_payload if workspace_payload is not None else EmptyData(),
        workspace_meta=snapshot_meta(workspace) or EmptyData(),
        analysis=AnalysisSummary.from_overview(reverse_payload),
        analysis_meta=snapshot_meta(reverse_snapshot) or EmptyData(),
    )
