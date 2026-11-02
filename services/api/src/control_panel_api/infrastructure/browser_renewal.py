"""Compose refresh ports without putting provider orchestration in a record repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from control_panel_api.application.browser_refresh import BrowserRefresh
from control_panel_api.infrastructure.browser_refresh import (
    RauthyIdentityRefresh,
    ValkeyRefreshSessions,
)
from control_panel_api.infrastructure.browser_storage import BrowserStorageContext

if TYPE_CHECKING:
    from control_panel_api._oidc import RauthyOidcAdapter


async def renew_browser_session(
    storage: BrowserStorageContext, ticket: str, provider: RauthyOidcAdapter
) -> int | None:
    return await BrowserRefresh(
        ValkeyRefreshSessions(storage),
        RauthyIdentityRefresh(provider),
        issuer=provider.issuer,
        client_id=provider.client_id,
    ).renew(ticket)
