from __future__ import annotations

import asyncio
from collections.abc import Sequence

from briareus_account_contracts import AccountPublic
from briareus_json_values import JsonObject, JsonValue, json_object

from control_panel_api.application.services import (
    AccountService,
    InvocationAuditService,
    SnapshotService,
)
from control_panel_api.domain.accounts import Provider
from control_panel_api.infrastructure.snapshot_worker import (
    REVERSE_OVERVIEW_KEY,
    WORKSPACE_STATS_KEY,
    snapshot_meta,
)


def _account_summary(accounts: Sequence[AccountPublic]) -> JsonObject:
    return {
        "total": len(accounts),
        "enabled": sum(1 for item in accounts if item.enabled),
        "by_provider": {
            provider.value: sum(
                1 for item in accounts if item.provider == provider.value and item.enabled
            )
            for provider in Provider
        },
    }


def _analysis_summary(project_items: list[JsonValue], worker_items: list[JsonValue]) -> JsonObject:
    return {
        "projects": len(project_items),
        "active_sessions": sum(
            1
            for item in project_items
            if isinstance(item, dict) and item.get("session") == "active"
        ),
        "workers": len(worker_items),
        "running_workers": sum(
            1 for item in worker_items if isinstance(item, dict) and bool(item.get("running"))
        ),
    }


async def build_dashboard_state(
    accounts_service: AccountService, audit: InvocationAuditService, snapshots: SnapshotService
) -> JsonObject:
    accounts, calls, workspace, reverse_snapshot = await asyncio.gather(
        asyncio.to_thread(accounts_service.list),
        asyncio.to_thread(audit.summary),
        asyncio.to_thread(snapshots.get, WORKSPACE_STATS_KEY),
        asyncio.to_thread(snapshots.get, REVERSE_OVERVIEW_KEY),
    )
    reverse_payload = reverse_snapshot.payload if reverse_snapshot is not None else {}
    projects = reverse_payload.get("projects")
    workers = reverse_payload.get("workers")
    project_items = projects if isinstance(projects, list) else []
    worker_items = workers if isinstance(workers, list) else []
    return {
        "accounts": _account_summary(accounts),
        "calls": json_object(calls, context="dashboard calls"),
        "workspace": workspace.payload if workspace is not None else {},
        "workspace_meta": snapshot_meta(workspace),
        "analysis": _analysis_summary(project_items, worker_items),
        "analysis_meta": snapshot_meta(reverse_snapshot),
    }
