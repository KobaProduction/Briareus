"""Process resource ownership and shutdown order, outside application scenarios."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI

from control_panel_api._api_configuration import ApiIdentity, ApiPeers
from control_panel_api._panel_events import panel_events
from control_panel_api._resource_broker import ResourceCredentialUnavailable, ResourceTokenBroker
from control_panel_api._resource_escrow import SessionResourceCredentials
from control_panel_api.infrastructure.human_web import PeerHumanEffectPermits


@dataclass(frozen=True, slots=True)
class ApiLifecycle:
    identity: ApiIdentity
    peers: ApiPeers

    def initialize(self, app: FastAPI) -> None:
        app.state.rauthy_admin = self.identity.admin
        app.state.rauthy_admin_state = self.identity.admin_state
        app.state.resource_credentials = None
        app.state.human_web_permits = (
            PeerHumanEffectPermits(self.peers.access.peer) if self.peers.access is not None else None
        )
        app.state.resource_broker_state = "unconfigured"
        provider, sessions = self.identity.provider, self.identity.sessions
        if sessions is None or provider is None:
            return
        try:
            broker = ResourceTokenBroker.from_environment(provider)
            app.state.resource_credentials = SessionResourceCredentials(
                sessions=sessions, provider=provider, broker=broker
            )
            app.state.resource_broker_state = "configured" if broker else "unconfigured"
        except ResourceCredentialUnavailable:
            app.state.resource_broker_state = "unavailable"

    async def close(self, app: FastAPI) -> None:
        app.state.human_web_permits = None
        await panel_events.close()
        for peer in (self.peers.terminal, self.peers.files, self.peers.web, self.peers.resources):
            if peer is not None:
                await peer.close()
        if self.peers.access is not None:
            await self.peers.access.close()
        if self.peers.platform is not None:
            await self.peers.platform.close()
        app.state.rauthy_admin = None
        app.state.rauthy_admin_state = None
        for dependency in (self.identity.admin, self.identity.sessions, self.identity.provider):
            if dependency is not None:
                await dependency.close()

    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        self.initialize(app)
        if self.identity.sessions is not None:
            await panel_events.start(self.identity.sessions.storage.client)
        try:
            yield
        finally:
            await self.close(app)
