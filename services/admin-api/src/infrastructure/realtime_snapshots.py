"""Read existing owner snapshots and encode their unchanged realtime envelope."""

from application.services import (
    AccountService,
    InvocationAuditService,
    OAuthSessionService,
    SnapshotService,
)
from dashboard_state import build_dashboard_state
from domain.realtime import BrowserUnavailable
from domain.telemetry import InvocationBatch
from realtime import RealtimeBus

from common.browser_contracts import BrowserStatus
from infrastructure.realtime_codec import RealtimeEnvelope, new_event, snapshot_event
from infrastructure.web import WebAdminClient


class LegacyRealtimeSnapshots:
    def __init__(
        self,
        bus: RealtimeBus,
        accounts: AccountService,
        audit: InvocationAuditService,
        oauth_sessions: OAuthSessionService,
        snapshots: SnapshotService,
        web: WebAdminClient,
    ) -> None:
        self._bus = bus
        self._accounts = accounts
        self._audit = audit
        self._oauth_sessions = oauth_sessions
        self._snapshots = snapshots
        self._web = web

    async def read(self, topic: str) -> RealtimeEnvelope | None:
        if topic == "mcp.calls":
            events = await self._audit.recent(limit=100)
            return new_event(
                topic, "snapshot", InvocationBatch(events=tuple(events), count=len(events))
            )
        if topic == "browser.runtime":
            return await self._browser()
        if topic == "system.metrics":
            data = await build_dashboard_state(
                self._accounts, self._audit, self._oauth_sessions, self._snapshots
            )
            return new_event(topic, "snapshot", data)
        cached = self._bus.snapshot(topic)
        if cached is not None:
            return snapshot_event(cached)
        return None

    async def _browser(self) -> RealtimeEnvelope:
        try:
            data: BrowserStatus | BrowserUnavailable = await self._web.status()
        except Exception as exc:
            data = BrowserUnavailable(error=str(exc))
        return new_event("browser.runtime", "snapshot", data)
