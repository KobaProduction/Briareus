"""Static Rauthy 0.37.1 confidential-client contract for Core resource exchange.

Provisioning uses the provider's authenticated admin-session API. This module
holds public configuration only, never human credentials or client secrets.
"""

from dataclasses import dataclass, fields

CLIENT_ID = "briareus-resource-broker"
CLIENT_NAME = "Briareus Resource Broker"
GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
HANDS = ("files", "terminal", "web", "svc", "infrastructure", "reverse", "serena")
SIGNATURE_ALGORITHM = "EdDSA"


@dataclass(frozen=True)
class ResourceBrokerConfiguration:
    """Provider-owned client fields approved for the server-only broker."""

    client_uri: str
    allowed_resources: tuple[str, ...]
    name: str = CLIENT_NAME
    confidential: bool = True
    enabled: bool = True
    redirect_uris: tuple[str, ...] = ()
    post_logout_redirect_uris: None = None
    allowed_origins: None = None
    flows_enabled: tuple[str, ...] = (GRANT,)
    access_token_alg: str = SIGNATURE_ALGORITHM
    id_token_alg: str = SIGNATURE_ALGORITHM
    auth_code_lifetime: int = 30
    access_token_lifetime: int = 90
    scopes: tuple[str, ...] = ("openid", "profile", "email")
    default_scopes: tuple[str, ...] = ("openid", "profile", "email")
    challenges: None = None
    force_mfa: bool = True
    contacts: None = None
    backchannel_logout_uri: None = None
    restrict_group_prefix: None = None
    claims: None = None
    claims_at_root: bool = False
    default_aud: None = None
    scim: None = None


def configuration(origin: str) -> ResourceBrokerConfiguration:
    if origin not in {"https://127.0.0.1", "https://briareus.koba-nexus.ru"}:
        raise ValueError("Approved Core realm required")
    return ResourceBrokerConfiguration(
        client_uri=origin + "/panel/",
        allowed_resources=tuple(origin + "/hands/" + hand + "/mcp" for hand in HANDS),
    )


def _matches_field(name: str, actual: object, wanted: object) -> bool:
    if name in {"flows_enabled", "allowed_resources", "scopes", "default_scopes"}:
        if not isinstance(actual, list) or not all(isinstance(item, str) for item in actual):
            return False
        return isinstance(wanted, tuple) and sorted(actual) == sorted(wanted)
    if wanted is None and name in {
        "post_logout_redirect_uris",
        "allowed_origins",
        "contacts",
        "challenges",
        "default_aud",
    }:
        return actual in (None, [])
    if isinstance(wanted, tuple):
        return isinstance(actual, list) and actual == list(wanted)
    return actual == wanted


def verify_configuration(value: object, origin: str) -> None:
    """Validate a provider response against the approved public configuration."""
    expected = configuration(origin)
    if not isinstance(value, dict) or value.get("id") != CLIENT_ID:
        raise ValueError("Wrong resource client identity")
    for field in fields(expected):
        wanted: object = getattr(expected, field.name)
        if not _matches_field(field.name, value.get(field.name), wanted):
            if field.name in {"flows_enabled", "allowed_resources", "scopes", "default_scopes"}:
                raise ValueError("Resource client scope differs from approved contract")
            raise ValueError("Resource client configuration differs from approved contract")
