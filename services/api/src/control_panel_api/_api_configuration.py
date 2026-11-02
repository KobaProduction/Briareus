"""Environment and injected dependency composition for the independent API owner."""

import os
from contextlib import suppress
from dataclasses import dataclass

from pydantic import SecretStr

from control_panel_api._oidc import RauthyOidcAdapter
from control_panel_api._oidc_browser import OidcBrowserSessionStore
from control_panel_api._oidc_membership import CurrentPlatformUserSource
from control_panel_api._oidc_origin_policy import PUBLIC_ORIGIN
from control_panel_api._platform_current_client import PrivatePlatformCurrentClient
from control_panel_api._platform_unix_peer import UnixPlatformPeer
from control_panel_api._rauthy_admin import RauthyAdminClient, RauthyAdminKeyRejected
from control_panel_api._rauthy_native_init import PinnedNativeRauthyInit
from control_panel_api._runtime_access_client import RuntimeAccessClient
from control_panel_api.application.approval_contracts import ApprovalSource
from runtime_peer import PeerClient, PeerIdentity


@dataclass(frozen=True, slots=True)
class PeerBinding:
    socket: str
    verify_key: str
    identity: str
    uid: int


def configured_peer(binding: PeerBinding) -> PeerClient | None:
    path = os.environ.get(binding.socket)
    if not path:
        return None
    return PeerClient(
        name="briareus:control-panel-api",
        signing_key_file=os.environ["PLATFORM_PANEL_SIGNING_KEY_FILE"],
        socket_path=path,
        owner=PeerIdentity.from_file(binding.identity, binding.uid, os.environ[binding.verify_key]),
    )


@dataclass(frozen=True, slots=True)
class ApiPeers:
    platform: UnixPlatformPeer | None
    access: RuntimeAccessClient | None
    terminal: PeerClient | None
    files: PeerClient | None
    web: PeerClient | None
    resources: PeerClient | None
    membership: CurrentPlatformUserSource | None
    approvals: ApprovalSource | None


def configured_platform(source: CurrentPlatformUserSource | None) -> UnixPlatformPeer | None:
    socket_path = os.environ.get("PLATFORM_PANEL_SOCKET", "")
    signing_key = os.environ.get("PLATFORM_PANEL_SIGNING_KEY_FILE", "")
    if source is not None or not (socket_path or signing_key):
        return None
    if not socket_path or not signing_key:
        raise ValueError("Platform socket and service signing key must be configured together")
    return UnixPlatformPeer(socket_path=socket_path, signing_key_file=signing_key)


def configured_peers(
    membership: CurrentPlatformUserSource | None, approvals: ApprovalSource | None
) -> ApiPeers:
    if os.environ.get("ACCESS_RUNTIME_SOCKET") and approvals is not None:
        raise ValueError("Access owner sources are mutually exclusive")
    access_peer = configured_peer(
        PeerBinding(
            "ACCESS_RUNTIME_SOCKET", "ACCESS_RUNTIME_VERIFY_KEY_FILE", "briareus:access", 1002
        )
    )
    access = RuntimeAccessClient(access_peer) if access_peer is not None else None
    terminal = files = web = None
    if access is not None:
        terminal = configured_peer(
            PeerBinding(
                "TERMINAL_CONTROLLER_SOCKET",
                "TERMINAL_CONTROLLER_VERIFY_KEY_FILE",
                "briareus:terminal",
                1003,
            )
        )
        files = configured_peer(
            PeerBinding(
                "FILES_RUNTIME_SOCKET", "FILES_RUNTIME_VERIFY_KEY_FILE", "briareus:files", 1004
            )
        )
        web = configured_peer(
            PeerBinding("WEB_RUNTIME_SOCKET", "WEB_RUNTIME_VERIFY_KEY_FILE", "briareus:web", 1005)
        )
    resources = configured_peer(
        PeerBinding(
            "RESOURCES_RUNTIME_SOCKET",
            "RESOURCES_RUNTIME_VERIFY_KEY_FILE",
            "briareus:resources",
            1006,
        )
    )
    platform = configured_platform(membership)
    return ApiPeers(
        platform,
        access,
        terminal,
        files,
        web,
        resources,
        PrivatePlatformCurrentClient(peer=platform) if platform is not None else membership,
        access if access is not None else approvals,
    )


def configured_provider(provider: RauthyOidcAdapter | None) -> RauthyOidcAdapter | None:
    if provider is not None:
        return provider
    issuer, client_id = os.environ.get("OIDC_ISSUER", ""), os.environ.get("OIDC_CLIENT_ID", "")
    if not issuer and not client_id:
        return None
    if not issuer or not client_id:
        raise RuntimeError("both OIDC_ISSUER and OIDC_CLIENT_ID must be configured")
    approved = (
        issuer.rstrip("/") == PUBLIC_ORIGIN + "/auth/v1" and client_id == "briareus-control-panel"
    )
    audience = os.environ.get("OIDC_RESOURCE_AUDIENCE") or None
    if audience is not None and (not approved or audience != PUBLIC_ORIGIN + "/hands/files/mcp"):
        raise ValueError("OIDC resource must match the approved issuer/client/Files realm")
    return RauthyOidcAdapter(issuer=issuer, client_id=client_id, resource_audience=audience)


@dataclass(frozen=True, slots=True)
class ApiIdentity:
    provider: RauthyOidcAdapter | None
    sessions: OidcBrowserSessionStore | None
    native: PinnedNativeRauthyInit | None
    admin: RauthyAdminClient | None
    admin_state: str


def configured_admin() -> tuple[RauthyAdminClient | None, str]:
    raw_key = os.environ.get("RAUTHY_ADMIN_API_KEY", "")
    if not raw_key:
        return None, "unconfigured"
    try:
        return RauthyAdminClient(api_key=SecretStr(raw_key)), "configured_unverified"
    except RauthyAdminKeyRejected:
        return None, "invalid_credential"


def configured_identity(
    provider: RauthyOidcAdapter | None,
    native: PinnedNativeRauthyInit | None,
    local_origin: str | None,
) -> ApiIdentity:
    if local_origin is not None and provider is None:
        raise ValueError("local test origin requires injected sandbox provider")
    if native is not None and (
        provider is None or (local_origin is None and native.issuer != PUBLIC_ORIGIN + "/auth/v1")
    ):
        raise ValueError("native Rauthy owner must be independently configured for its exact realm")
    managed = configured_provider(provider)
    if (
        native is None
        and local_origin is None
        and managed is not None
        and managed.issuer == PUBLIC_ORIGIN + "/auth/v1"
        and managed.client_id == "briareus-control-panel"
    ):
        native = PinnedNativeRauthyInit.for_public_dev()
    sessions = None
    password = os.environ.get("OIDC_SESSION_VALKEY_PASSWORD", "")
    if password:
        with suppress(ValueError):
            sessions = OidcBrowserSessionStore(password=SecretStr(password))
    admin, state = configured_admin()
    return ApiIdentity(managed, sessions, native, admin, state)
