"""Concrete BFF router wiring; protocols and scenarios remain in their own layers."""

from fastapi import FastAPI

from control_panel_api._api_configuration import ApiIdentity, ApiPeers
from control_panel_api._oidc import RauthyOidcAdapter
from control_panel_api._oidc_browser import OidcBrowserSessionStore, oidc_browser_router
from control_panel_api._oidc_catalog import TrustedCatalogReadPort
from control_panel_api._oidc_files_content import TrustedFilesContentOwner
from control_panel_api._oidc_membership import platform_membership_router
from control_panel_api._oidc_native_login import native_login_router
from control_panel_api._oidc_native_start import native_login_start_router
from control_panel_api._oidc_password_setup import password_setup_router
from control_panel_api._rauthy_native_init import PinnedNativeRauthyInit
from control_panel_api.presentation.api_status import (
    install_native_unavailable,
    install_public_status,
    install_unconfigured,
)


def install_native(
    app: FastAPI,
    provider: RauthyOidcAdapter,
    sessions: OidcBrowserSessionStore,
    native: PinnedNativeRauthyInit,
    local_origin: str | None,
) -> None:
    app.include_router(
        password_setup_router(
            native=native, provider=provider, sessions=sessions, test_only_local_origin=local_origin
        )
    )
    app.include_router(
        native_login_start_router(
            provider=provider,
            transactions=sessions,
            native_init=native,
            test_only_local_origin=local_origin,
        )
    )
    app.include_router(
        native_login_router(
            provider=provider,
            transactions=sessions,
            native_provider=native,
            test_only_local_origin=local_origin,
        )
    )


def install_routes(
    app: FastAPI,
    identity: ApiIdentity,
    peers: ApiPeers,
    catalog: TrustedCatalogReadPort | None,
    files_content: TrustedFilesContentOwner | None,
    local_origin: str | None,
) -> None:
    provider, sessions, native = identity.provider, identity.sessions, identity.native
    if native is None or sessions is None or provider is None:
        install_native_unavailable(app)
    install_public_status(app, provider)
    if provider is None or sessions is None:
        install_unconfigured(app)
        return
    app.include_router(oidc_browser_router(provider, sessions, test_only_local_origin=local_origin))
    if native is not None:
        install_native(app, provider, sessions, native, local_origin)
    app.include_router(
        platform_membership_router(
            sessions,
            source=peers.membership,
            approval_source=peers.approvals,
            catalog_source=catalog,
            files_content_source=files_content,
            resource_audience=provider.resource_audience,
            test_only_local_origin=local_origin,
            expected_issuer=provider.issuer,
            expected_client_id=provider.client_id,
            management_peer=peers.platform,
            terminal_peer=peers.terminal,
            files_peer=peers.files,
            web_peer=peers.web,
            connections_peer=peers.resources,
        )
    )
