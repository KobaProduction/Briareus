from __future__ import annotations

import asyncio
import logging

from briareus_service_discovery import ServiceDiscovery

from control_panel_api.application.admin_ports import AnalysisAdminPort, FileAdminPort
from control_panel_api.application.services import SnapshotService
from control_panel_api.domain.snapshots import (
    CachedSnapshot,
    CoverageSnapshotParameters,
    SnapshotMetadata,
)

logger = logging.getLogger(__name__)

WORKSPACE_STATS_KEY = "workspace:stats"
REVERSE_OVERVIEW_KEY = "reverse:overview"
WORKSPACE_STATS_REFRESH_SECONDS = 5 * 60
REVERSE_OVERVIEW_REFRESH_SECONDS = 30
QUICK_COVERAGE_REFRESH_SECONDS = 10 * 60
FULL_COVERAGE_REFRESH_SECONDS = 30 * 60


class SnapshotRefresher:
    def __init__(
        self,
        snapshots: SnapshotService,
        files: FileAdminPort,
        reverse: AnalysisAdminPort,
        *,
        discovery: ServiceDiscovery | None = None,
    ) -> None:
        self.snapshots = snapshots
        self.files = files
        self.reverse = reverse
        self.discovery = discovery
        self._coverage_wakeup = asyncio.Event()

    async def ensure_base_snapshots(self) -> None:
        await asyncio.to_thread(
            self.snapshots.ensure,
            WORKSPACE_STATS_KEY,
            category="workspace_stats",
            refresh_after_seconds=WORKSPACE_STATS_REFRESH_SECONDS,
        )
        await asyncio.to_thread(
            self.snapshots.ensure,
            REVERSE_OVERVIEW_KEY,
            category="reverse_overview",
            refresh_after_seconds=REVERSE_OVERVIEW_REFRESH_SECONDS,
        )

    async def _refresh_workspace_once(self) -> None:
        if self.discovery is not None and not await self.discovery.connected("server"):
            return
        due = await asyncio.to_thread(self.snapshots.due, "workspace_stats", limit=1)
        if not due:
            return
        snapshot = due[0]
        await asyncio.to_thread(self.snapshots.mark_attempt, snapshot.key)
        try:
            payload = await asyncio.to_thread(self.files.stats)
            await asyncio.to_thread(
                self.snapshots.store_success,
                snapshot.key,
                payload,
            )
        except Exception as exc:
            logger.exception("workspace snapshot refresh failed")
            await asyncio.to_thread(self.snapshots.store_error, snapshot.key, exc)

    async def _refresh_reverse_once(self) -> None:
        if self.discovery is not None and not await self.discovery.connected("ghidra"):
            return
        due = await asyncio.to_thread(self.snapshots.due, "reverse_overview", limit=1)
        if not due:
            return
        snapshot = due[0]
        await asyncio.to_thread(self.snapshots.mark_attempt, snapshot.key)
        try:
            payload = await self.reverse.overview()
            await asyncio.to_thread(
                self.snapshots.store_success,
                snapshot.key,
                payload,
            )
        except Exception as exc:
            logger.exception("reverse overview snapshot refresh failed")
            await asyncio.to_thread(self.snapshots.store_error, snapshot.key, exc)

    async def _refresh_coverage_once(self) -> bool:
        if self.discovery is not None and not await self.discovery.connected("ghidra"):
            return False
        due = await asyncio.to_thread(
            self.snapshots.due,
            "reverse_coverage",
            retry_after_seconds=60,
            limit=100,
        )
        if not due:
            return False
        snapshot = due[0]
        parameters = snapshot.parameters
        if not isinstance(parameters, CoverageSnapshotParameters):
            raise ValueError("coverage snapshot parameters are invalid")
        project_id, program, full_mode = parameters.project_id, parameters.program, parameters.full
        await asyncio.to_thread(self.snapshots.mark_attempt, snapshot.key)
        try:
            payload = await self.reverse.coverage(project_id, program, full=full_mode)
            await asyncio.to_thread(
                self.snapshots.store_success,
                snapshot.key,
                payload,
            )
        except Exception as exc:
            logger.exception(
                "reverse coverage snapshot refresh failed project=%s program=%s full=%s",
                project_id,
                program,
                full_mode,
            )
            await asyncio.to_thread(self.snapshots.store_error, snapshot.key, exc)
        return True

    def notify_coverage_requested(self) -> None:
        self._coverage_wakeup.set()

    async def workspace_loop(self) -> None:
        while True:
            await self._refresh_workspace_once()
            await asyncio.sleep(60)

    async def reverse_loop(self) -> None:
        while True:
            await self._refresh_reverse_once()
            await asyncio.sleep(REVERSE_OVERVIEW_REFRESH_SECONDS)

    async def coverage_loop(self) -> None:
        while True:
            while await self._refresh_coverage_once():
                pass
            try:
                await asyncio.wait_for(self._coverage_wakeup.wait(), timeout=60)
            except TimeoutError:
                pass
            finally:
                self._coverage_wakeup.clear()


def coverage_snapshot_key(project_id: str, program: str, *, full: bool) -> str:
    import hashlib

    mode = "full" if full else "quick"
    digest = hashlib.sha256(f"{project_id}\0{program}\0{mode}".encode()).hexdigest()[:24]
    return f"reverse:coverage:{mode}:{digest}"


def coverage_refresh_seconds(*, full: bool) -> int:
    return FULL_COVERAGE_REFRESH_SECONDS if full else QUICK_COVERAGE_REFRESH_SECONDS


def snapshot_meta(snapshot: CachedSnapshot | None) -> SnapshotMetadata | None:
    if snapshot is None:
        return None
    age = snapshot.age_seconds()
    return SnapshotMetadata(
        status=snapshot.status,
        updated_at=snapshot.updated_at.isoformat() if snapshot.updated_at else None,
        attempted_at=snapshot.attempted_at.isoformat() if snapshot.attempted_at else None,
        age_seconds=round(age, 1) if age is not None else None,
        stale=snapshot.stale(),
        error_type=snapshot.error_type,
        error_message=snapshot.error_message,
    )
