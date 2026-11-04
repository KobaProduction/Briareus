from __future__ import annotations

import hmac
from typing import Annotated

from briareus_account_contracts import AccountList, GitHubAuthenticatedReaderSync
from briareus_invocation_events import InvocationEvent, InvocationEventBatch
from briareus_json_values import JsonObject
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from control_panel_api.application.services import (
    AccountService,
    InvocationAuditService,
    RuntimeSettingsService,
)
from control_panel_api.domain.accounts import Account, AuthType, Provider
from control_panel_api.domain.telemetry import Invocation


class ApiServices:
    def __init__(
        self,
        accounts: AccountService,
        audit: InvocationAuditService,
        runtime_settings: RuntimeSettingsService,
        service_token: str,
    ) -> None:
        self.accounts = accounts
        self.audit = audit
        self.runtime_settings = runtime_settings
        self.service_token = service_token


class InternalRoutes:
    def __init__(self, services: ApiServices) -> None:
        self.services = services

    def register(self, router: APIRouter) -> None:
        router.add_api_route("/accounts", self.list_accounts, methods=["GET"])
        router.add_api_route("/accounts/{selector}/resolve", self.resolve_account, methods=["GET"])
        router.add_api_route(
            "/accounts/github/authenticated-reader",
            self.sync_github_authenticated_reader,
            methods=["PUT"],
        )
        router.add_api_route(
            "/runtime-settings/terminal", self.terminal_runtime_settings, methods=["GET"]
        )
        router.add_api_route("/runtime-settings/mcp", self.mcp_runtime_settings, methods=["GET"])
        router.add_api_route(
            "/runtime-settings/github", self.github_runtime_settings, methods=["GET"]
        )
        router.add_api_route(
            "/runtime-settings/gitlab", self.gitlab_runtime_settings, methods=["GET"]
        )
        router.add_api_route(
            "/runtime-settings/browser", self.browser_runtime_settings, methods=["GET"]
        )
        router.add_api_route(
            "/runtime-settings/browser-launcher",
            self.browser_launcher_runtime_settings,
            methods=["GET"],
        )
        router.add_api_route("/events", self.record_event, methods=["POST"], status_code=204)
        router.add_api_route(
            "/events/batch", self.record_event_batch, methods=["POST"], status_code=204
        )
        router.add_api_route("/events/recent", self.recent_events, methods=["GET"])

    def authorize(self, authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {self.services.service_token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")

    def list_accounts(self, provider: Annotated[Provider | None, Query()] = None) -> JsonObject:
        accounts = self.services.accounts.list(provider=provider)
        return AccountList(accounts=accounts, count=len(accounts)).to_json()

    def resolve_account(self, selector: str, provider: Provider) -> JsonObject:
        try:
            return self.services.accounts.resolve(selector, provider=provider).model_dump(
                mode="json"
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def sync_github_authenticated_reader(
        self, payload: GitHubAuthenticatedReaderSync
    ) -> JsonObject:
        try:
            account = self.services.accounts.get(
                "authenticated", provider=Provider.GITHUB, enabled_only=False
            )
        except KeyError:
            saved = self.services.accounts.create(
                Account(
                    alias="authenticated",
                    provider=Provider.GITHUB,
                    auth_type=AuthType.GITHUB_TOKEN,
                    enabled=True,
                ),
                credential=payload.token,
            )
            return {**saved.public(), "login": payload.login, "synced": True}
        if account.auth_type is not AuthType.GITHUB_TOKEN:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="authenticated GitHub reader exists with incompatible auth_type",
            )
        if not account.enabled:
            account.enabled = True
            account = self.services.accounts.update(account)
        self.services.accounts.set_credential(account.id, payload.token, provider=Provider.GITHUB)
        return {**account.public(), "login": payload.login, "synced": True}

    def terminal_runtime_settings(self) -> JsonObject:
        return self.services.runtime_settings.terminal_policy().to_json()

    def mcp_runtime_settings(self) -> JsonObject:
        return self.services.runtime_settings.mcp_policy().to_json()

    def github_runtime_settings(self) -> JsonObject:
        return self.services.runtime_settings.github_policy().to_json()

    def gitlab_runtime_settings(self) -> JsonObject:
        return self.services.runtime_settings.gitlab_policy().to_json()

    def browser_runtime_settings(self) -> JsonObject:
        return self.services.runtime_settings.browser_policy().to_json()

    def browser_launcher_runtime_settings(self) -> JsonObject:
        return self.services.runtime_settings.browser_launcher_policy().to_json()

    def record_event(self, event: InvocationEvent) -> None:
        self.services.audit.record(Invocation.model_validate(event.model_dump()))

    def record_event_batch(self, batch: InvocationEventBatch) -> None:
        self.services.audit.record_many(
            [Invocation.model_validate(event.model_dump()) for event in batch.events]
        )

    def recent_events(self, limit: Annotated[int, Query(ge=1, le=1000)] = 100) -> JsonObject:
        events = self.services.audit.recent(limit=limit)
        return {"events": [event.model_dump(mode="json") for event in events], "count": len(events)}


def build_internal_router(services: ApiServices) -> APIRouter:
    routes = InternalRoutes(services)
    router = APIRouter(
        prefix="/internal", tags=["internal"], dependencies=[Depends(routes.authorize)]
    )
    routes.register(router)
    return router
