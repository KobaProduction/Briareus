"""Compose scoped owner journal adapters for one authenticated Panel connection."""

from collections.abc import AsyncIterator

from control_panel_api.domain.platform_authority import ResolvedPlatformUser
from runtime_peer import PeerClient

from ._panel_events import panel_events
from ._platform_unix_peer import UnixPlatformPeer
from ._runtime_access_client import RuntimeAccessClient
from .application.owner_event_relay import OwnerEventRelay, RelayNotice
from .domain.owner_events import EventAuthority, EventProject
from .infrastructure.owner_journals import PanelOwnerEventSink, PrivateOwnerJournals


class OwnerSignals:
    def __init__(
        self,
        access: RuntimeAccessClient | None,
        platform: UnixPlatformPeer | None,
        resources: PeerClient | None,
    ) -> None:
        self.access, self.platform, self.resources = access, platform, resources
        self.relay = OwnerEventRelay()
        self.windows, self.health = self.relay.windows, self.relay.health

    async def read(self, proof: ResolvedPlatformUser) -> AsyncIterator[RelayNotice]:
        authority = EventAuthority(
            proof.user_uuid,
            proof.role == "operator",
            proof.expires_at,
            tuple(
                EventProject(
                    item.project_uuid,
                    "use_resources" in item.permissions,
                    "approve_agent_session" in item.permissions,
                )
                for item in proof.projects
            ),
        )
        journal = PrivateOwnerJournals(proof, self.access, self.platform, self.resources)
        async for notice in self.relay.read(
            authority,
            available=journal.available,
            journal=journal,
            sink=PanelOwnerEventSink(panel_events),
        ):
            yield notice
