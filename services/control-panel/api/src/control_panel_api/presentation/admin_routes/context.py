from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from time import monotonic

from fastapi import HTTPException, Request, status

from control_panel_api.application.identity import PanelIdentityService
from control_panel_api.presentation.identity import request_session, require_mutation
from control_panel_api.settings import ControlPanelSettings

from .contracts import WebApiServices


@dataclass
class WebApiContext:
    settings: ControlPanelSettings
    services: WebApiServices | None
    identity: PanelIdentityService
    public_origin: str
    settings_update_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    candidate_verify_slots: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(4))
    candidate_verify_rate_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    candidate_verify_attempts: dict[str, deque[float]] = field(default_factory=dict)

    def authenticated_username(self, request: Request) -> str | None:
        session = request_session(request, self.identity)
        return session.grant.subject if session is not None else None

    def require_user(self, request: Request) -> str:
        username = self.authenticated_username(request)
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
        return username

    def available(self) -> WebApiServices:
        if self.services is None:
            raise HTTPException(status_code=503, detail="management API services unavailable")
        return self.services

    def mutation(self, request: Request) -> WebApiServices:
        require_mutation(request, self.identity, self.public_origin)
        return self.available()

    async def publish_management_event(
        self, api: WebApiServices, event_type: str, data: object
    ) -> None:
        if api.realtime is not None:
            await api.realtime.publish("management.events", event_type, data)

    async def enforce_candidate_verify_rate(self, request: Request) -> None:
        username = self.authenticated_username(request) or "unknown"
        client_host = request.client.host if request.client is not None else "unknown"
        key = f"{username}:{client_host}"
        now = monotonic()
        cutoff = now - 60.0
        async with self.candidate_verify_rate_lock:
            bucket = self.candidate_verify_attempts.setdefault(key, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= 20:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="candidate verification rate limit exceeded",
                    headers={"Retry-After": "60"},
                )
            bucket.append(now)
