"""Authenticated internal HTTP adapters; account orchestration belongs to application."""

from __future__ import annotations

import hmac
from typing import Annotated

from application.account_views import public_account
from application.authenticated_reader import ReaderAuthenticationConflict, SyncAuthenticatedReader
from application.internal_views import (
    AuthenticatedReaderView,
    InvocationList,
    OAuthSessionList,
    OAuthSessionView,
)
from application.invocation_contracts import InvocationDocument, invocation_from_event
from application.services import (
    AccountService,
    InvocationAuditService,
    OAuthSessionService,
    RuntimeSettingsService,
)
from domain.accounts import Provider
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from common.account_contracts import (
    AccountList,
    GitHubAuthenticatedReaderSync,
    InvocationEvent,
    InvocationEventBatch,
    ResolvedAccount,
)
from common.oauth_session_contracts import OAuthSessionEvent
from common.runtime_policy_contracts import (
    BrowserLauncherPolicy,
    BrowserRuntimePolicy,
    GitHubRuntimePolicy,
    GitLabRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)


class ApiServices:
    def __init__(
        self,
        accounts: AccountService,
        audit: InvocationAuditService,
        oauth_sessions: OAuthSessionService,
        runtime_settings: RuntimeSettingsService,
        service_token: str,
    ) -> None:
        if not service_token.strip():
            raise ValueError("Internal Admin API requires a nonblank service token")
        self.accounts = accounts
        self.audit = audit
        self.oauth_sessions = oauth_sessions
        self.runtime_settings = runtime_settings
        self.service_token = service_token


class InternalApiEndpoints:
    def __init__(self, services: ApiServices) -> None:
        self.services = services
        self.reader = SyncAuthenticatedReader(services.accounts)

    def authorize(self, authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {self.services.service_token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")

    async def list_accounts(
        self, provider: Annotated[Provider | None, Query()] = None
    ) -> AccountList:
        accounts = await self.services.accounts.list(provider=provider)
        return AccountList(accounts=accounts, count=len(accounts))

    async def resolve_account(self, selector: str, provider: Provider) -> ResolvedAccount:
        try:
            return await self.services.accounts.resolve(selector, provider=provider)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def sync_github_authenticated_reader(
        self, payload: GitHubAuthenticatedReaderSync
    ) -> AuthenticatedReaderView:
        try:
            account = await self.reader.execute(payload.token)
        except ReaderAuthenticationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return AuthenticatedReaderView.from_public(public_account(account), login=payload.login)

    async def terminal_runtime_settings(self) -> TerminalRuntimePolicy:
        return await self.services.runtime_settings.terminal_policy()

    async def mcp_runtime_settings(self) -> McpRuntimePolicy:
        return await self.services.runtime_settings.mcp_policy()

    async def github_runtime_settings(self) -> GitHubRuntimePolicy:
        return await self.services.runtime_settings.github_policy()

    async def gitlab_runtime_settings(self) -> GitLabRuntimePolicy:
        return await self.services.runtime_settings.gitlab_policy()

    async def browser_runtime_settings(self) -> BrowserRuntimePolicy:
        return await self.services.runtime_settings.browser_policy()

    async def browser_launcher_settings(self) -> BrowserLauncherPolicy:
        return await self.services.runtime_settings.browser_launcher_policy()

    async def record_event(self, event: InvocationEvent) -> None:
        await self.services.audit.record(invocation_from_event(event))

    async def record_event_batch(self, batch: InvocationEventBatch) -> None:
        await self.services.audit.record_many(
            [invocation_from_event(event) for event in batch.events]
        )

    async def record_oauth_session(self, event: OAuthSessionEvent) -> None:
        await self.services.oauth_sessions.record(event)

    async def recent_oauth_sessions(
        self, limit: Annotated[int, Query(ge=1, le=1000)] = 200
    ) -> OAuthSessionList:
        sessions = await self.services.oauth_sessions.recent(limit=limit)
        return OAuthSessionList(
            sessions=[OAuthSessionView.from_record(session) for session in sessions],
            count=len(sessions),
        )

    async def recent_events(
        self, limit: Annotated[int, Query(ge=1, le=1000)] = 100
    ) -> InvocationList:
        events = await self.services.audit.recent(limit=limit)
        return InvocationList(
            events=[InvocationDocument(root=event) for event in events], count=len(events)
        )


def build_internal_router(services: ApiServices) -> APIRouter:
    endpoints = InternalApiEndpoints(services)
    router = APIRouter(
        prefix="/internal", tags=["internal"], dependencies=[Depends(endpoints.authorize)]
    )
    router.add_api_route("/accounts", endpoints.list_accounts, methods=["GET"])
    router.add_api_route("/accounts/{selector}/resolve", endpoints.resolve_account, methods=["GET"])
    router.add_api_route(
        "/accounts/github/authenticated-reader",
        endpoints.sync_github_authenticated_reader,
        methods=["PUT"],
    )
    router.add_api_route(
        "/runtime-settings/terminal", endpoints.terminal_runtime_settings, methods=["GET"]
    )
    router.add_api_route("/runtime-settings/mcp", endpoints.mcp_runtime_settings, methods=["GET"])
    router.add_api_route(
        "/runtime-settings/github", endpoints.github_runtime_settings, methods=["GET"]
    )
    router.add_api_route(
        "/runtime-settings/gitlab", endpoints.gitlab_runtime_settings, methods=["GET"]
    )
    router.add_api_route(
        "/runtime-settings/browser", endpoints.browser_runtime_settings, methods=["GET"]
    )
    router.add_api_route(
        "/runtime-settings/browser-launcher", endpoints.browser_launcher_settings, methods=["GET"]
    )
    router.add_api_route("/events", endpoints.record_event, methods=["POST"], status_code=204)
    router.add_api_route(
        "/events/batch", endpoints.record_event_batch, methods=["POST"], status_code=204
    )
    router.add_api_route(
        "/oauth-sessions/events", endpoints.record_oauth_session, methods=["POST"], status_code=204
    )
    router.add_api_route("/oauth-sessions/recent", endpoints.recent_oauth_sessions, methods=["GET"])
    router.add_api_route("/events/recent", endpoints.recent_events, methods=["GET"])
    return router
