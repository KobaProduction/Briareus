"""Independent Control Panel API composition root."""

from fastapi import FastAPI

from control_panel_api._api_configuration import configured_identity, configured_peers
from control_panel_api._api_lifecycle import ApiLifecycle
from control_panel_api._api_routes import install_routes
from control_panel_api._oidc import RauthyOidcAdapter
from control_panel_api._oidc_catalog import TrustedCatalogReadPort
from control_panel_api._oidc_files_content import TrustedFilesContentOwner
from control_panel_api._oidc_membership import CurrentPlatformUserSource
from control_panel_api._rauthy_native_init import PinnedNativeRauthyInit
from control_panel_api.application.approval_contracts import ApprovalSource
from control_panel_api.presentation.api_status import (
    OidcBrowserConfiguration as OidcBrowserConfiguration,
)


def create_control_panel_api(
    *,
    provider: RauthyOidcAdapter | None = None,
    membership_source: CurrentPlatformUserSource | None = None,
    approval_source: ApprovalSource | None = None,
    catalog_source: TrustedCatalogReadPort | None = None,
    files_content_source: TrustedFilesContentOwner | None = None,
    test_only_local_origin: str | None = None,
    native_init: PinnedNativeRauthyInit | None = None,
) -> FastAPI:
    peers = configured_peers(membership_source, approval_source)
    identity = configured_identity(provider, native_init, test_only_local_origin)
    lifecycle = ApiLifecycle(identity, peers)
    app = FastAPI(
        title="Briareus Control Panel API",
        version="0.1.0",
        lifespan=lifecycle.lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    install_routes(
        app, identity, peers, catalog_source, files_content_source, test_only_local_origin
    )
    return app


app = create_control_panel_api()
