"""Source-verified Rauthy v0.37.1 public Admin REST privacy slices.

Provider login, OAuth/OIDC, recovery and user self-service remain upstream.
Only independently confirmed privileged handler routes are filtered here;
the Panel BFF uses separate private Rauthy provider transport.
Source: upstream sebadob/rauthy tag v0.37.1 src/api/src/*.rs.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote

RouteDisposition = Literal["forward", "bad_path", "private_admin"]
_BAD_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")
_FORBIDDEN_ESCAPE = ("%25", "%2f", "%5c", "%00")
_ADMIN_ONLY_NAMESPACES = frozenset(
    {
        "admin",
        "api_keys",
        "backup",
        "blacklist",
        "email",
        "events",
        "groups",
        "roles",
        "scopes",
        "sessions",
    }
)
_ADMIN_PROVIDER_ROUTES = frozenset({"create", "lookup"})
_ADMIN_SINGLE_ROUTES = frozenset(
    {"auth_check_admin", "search", "login_time", "password_hash_times"}
)


@dataclass(frozen=True, slots=True)
class _ProviderRoute:
    namespace: str
    remaining: tuple[str, ...]
    method: str


def _parse_provider_route(
    path: str, method: str
) -> _ProviderRoute | Literal["bad_path", "forward"]:
    folded = path.casefold()
    if _BAD_ESCAPE.search(path) or any(encoded in folded for encoded in _FORBIDDEN_ESCAPE):
        return "bad_path"
    canonical = unquote(path)
    if (
        "�" in canonical
        or "//" in canonical
        or any(segment in {".", ".."} for segment in canonical.split("/"))
    ):
        return "bad_path"
    parts = canonical.rstrip("/").casefold().split("/")
    if parts[:3] != ["", "auth", "v1"] or len(parts) < 4:
        return "forward"
    return _ProviderRoute(parts[3], tuple(parts[4:]), method.upper())


def _users_private(route: _ProviderRoute) -> bool:
    remaining = route.remaining
    if not remaining or remaining[0] in {"attr", "email"}:
        # Collection management, attribute schemas and arbitrary e-mail lookup.
        return True
    # Self-service has /users/{id}/self, rather than direct user mutation.
    return len(remaining) == 1 and route.method in {"PUT", "PATCH", "DELETE"}


def _clients_private(route: _ProviderRoute) -> bool:
    remaining = route.remaining
    if not remaining:
        # Dynamic registration has the separate /clients_dyn namespace.
        return True
    if remaining == ("validate_uri",):
        return route.method != "POST"
    if len(remaining) == 1:
        return route.method in {"GET", "PUT", "DELETE"}
    if len(remaining) == 2:
        # Branding GET, forward_auth and callbacks remain available to login.
        return remaining[1] == "secret" or (
            remaining[1] in {"logo", "favicon"} and route.method != "GET"
        )
    return False


def _providers_private(route: _ProviderRoute) -> bool:
    remaining = route.remaining
    if not remaining or remaining[0] in _ADMIN_PROVIDER_ROUTES:
        return True
    if len(remaining) == 1 and route.method in {"PUT", "DELETE"}:
        # Preserve the current link exception for both methods.
        return remaining[0] != "link"
    if len(remaining) == 2:
        return remaining[1] == "delete_safe" or (remaining[1] == "img" and route.method != "GET")
    # Minimal, login, callback, link and image GET remain provider-owned.
    return False


def _pam_hosts_private(route: _ProviderRoute) -> bool:
    remaining = route.remaining
    if len(remaining) == 1:
        return True
    if remaining[1] == "user_access":
        return False
    return (len(remaining) == 2 and route.method in {"GET", "PUT", "DELETE"}) or (
        len(remaining) >= 3 and remaining[2] == "secret"
    )


def _pam_users_private(route: _ProviderRoute) -> bool:
    remaining = route.remaining
    if len(remaining) == 1:
        return True
    if remaining[1] in {"self", "authorized_keys"}:
        return False
    return (len(remaining) == 2 and route.method in {"GET", "PUT", "DELETE"}) or (
        len(remaining) >= 3 and remaining[2] == "authorized_key"
    )


def _pam_private(route: _ProviderRoute) -> bool:
    if not route.remaining:
        return False
    section = route.remaining[0]
    if section in {"emails_unlinked", "groups"}:
        return True
    if section == "hosts":
        return _pam_hosts_private(route)
    if section == "users":
        return _pam_users_private(route)
    # Login, MFA, password, preflight, getent and validate stay provider-owned.
    return False


def _other_routes_private(route: _ProviderRoute) -> bool:
    remaining = route.remaining
    if route.namespace == "kv":
        return bool(remaining and remaining[0] == "ns")
    if route.namespace == "oidc":
        return remaining == ("rotate_jwk",) and route.method == "POST"
    if route.namespace in {"theme", "password_policy"}:
        return route.method != "GET"
    if route.namespace == "tos":
        return not remaining or remaining[0] == "user"
    if route.namespace == "encryption":
        return bool(remaining and remaining[0] in {"keys", "migrate"})
    return False


_NAMESPACE_POLICIES: tuple[tuple[str, Callable[[_ProviderRoute], bool]], ...] = (
    ("users", _users_private),
    ("clients", _clients_private),
    ("providers", _providers_private),
    ("pam", _pam_private),
)


def classify_rauthy_public_path(path: str, method: str) -> RouteDisposition:
    """Apply the pinned provider privacy policy without changing its public paths."""
    route = _parse_provider_route(path, method)
    if isinstance(route, str):
        return route
    if route.namespace in _ADMIN_ONLY_NAMESPACES or route.namespace in _ADMIN_SINGLE_ROUTES:
        # The Admin HTML and exclusively privileged REST namespaces are private.
        return "private_admin"
    for namespace, policy in _NAMESPACE_POLICIES:
        if route.namespace == namespace:
            return "private_admin" if policy(route) else "forward"
    return "private_admin" if _other_routes_private(route) else "forward"
