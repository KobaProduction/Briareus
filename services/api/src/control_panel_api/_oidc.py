"""Compatible entrypoints for pinned provider capabilities and canonical OIDC contracts."""

from control_panel_api._oidc_id_token import verify_rauthy_id_token as verify_rauthy_id_token
from control_panel_api.application.oidc_provider_contracts import OidcDiscovery as OidcDiscovery
from control_panel_api.application.oidc_provider_contracts import (
    PublicOidcConfiguration as PublicOidcConfiguration,
)
from control_panel_api.application.oidc_provider_contracts import (
    UnverifiedOidcTokenResponse as UnverifiedOidcTokenResponse,
)
from control_panel_api.domain.oidc_identity import (
    OidcAuthorizationAttempt as OidcAuthorizationAttempt,
)
from control_panel_api.domain.oidc_identity import OidcIdentityRejected as OidcIdentityRejected
from control_panel_api.domain.oidc_identity import (
    OidcProviderUnavailable as OidcProviderUnavailable,
)
from control_panel_api.domain.oidc_identity import VerifiedOidcIdentity as VerifiedOidcIdentity
from control_panel_api.domain.oidc_identity import VerifiedOidcLogin as VerifiedOidcLogin
from control_panel_api.domain.oidc_provider import is_https_url as _is_https_url
from control_panel_api.domain.oidc_provider import rauthy_endpoint as _rauthy_endpoint
from control_panel_api.infrastructure.oidc_provider import RauthyOidcAdapter as RauthyOidcAdapter
from control_panel_api.infrastructure.oidc_provider import pkce_s256 as _pkce_s256

__all__ = [
    "OidcAuthorizationAttempt",
    "OidcDiscovery",
    "OidcIdentityRejected",
    "OidcProviderUnavailable",
    "PublicOidcConfiguration",
    "RauthyOidcAdapter",
    "UnverifiedOidcTokenResponse",
    "VerifiedOidcIdentity",
    "VerifiedOidcLogin",
    "_is_https_url",
    "_pkce_s256",
    "_rauthy_endpoint",
    "verify_rauthy_id_token",
]
