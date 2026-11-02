"""Prepare a typed revocable browser record before its persistence boundary."""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from control_panel_api.domain.oidc_identity import (
    OidcSessionStoreUnavailable,
    PrivateOidcResourceCredential,
    VerifiedOidcIdentity,
    VerifiedRefreshCredential,
)
from control_panel_api.infrastructure.browser_records import (
    StoredBrowserRefresh,
    StoredBrowserResource,
    StoredBrowserSession,
    valid_resource_type,
)

_MAX_IDENTITY_SECONDS = 900


@dataclass(frozen=True, slots=True)
class PreparedBrowserSession:
    ticket: str
    seconds: int
    record: StoredBrowserSession
    deadline: datetime


def prepare_browser_session(
    identity: VerifiedOidcIdentity,
    *,
    resource: PrivateOidcResourceCredential | None = None,
    refresh: VerifiedRefreshCredential | None = None,
) -> PreparedBrowserSession:
    now = datetime.now(UTC)
    if resource is not None and (
        not valid_resource_type(resource)
        or resource.issuer != identity.issuer
        or resource.subject != identity.subject
        or resource.client_id != identity.client_id
        or resource.expires_at < identity.expires_at
        or resource.expires_at <= now
    ):
        raise OidcSessionStoreUnavailable("resource bearer not bound to current browser identity")
    seconds = min(int((identity.expires_at - now).total_seconds()), _MAX_IDENTITY_SECONDS)
    if seconds < 1:
        raise OidcSessionStoreUnavailable("Rauthy identity already expired")
    ticket = secrets.token_urlsafe(48)
    # The opaque session expires at the earlier of signed ID token expiry
    # and the private Valkey maximum; /session and /me must report the
    # same effective limit as the actual revocable browser cookie.
    expires_at = min(identity.expires_at, now + timedelta(seconds=seconds))
    deadline = expires_at
    if refresh is not None:
        deadline = min(refresh.expires_at, now + timedelta(hours=8))
        seconds = int((deadline - now).total_seconds())
        if seconds < 1:
            raise OidcSessionStoreUnavailable("Provider refresh already expired")
        expires_at = identity.expires_at
    stored_refresh = (
        StoredBrowserRefresh(
            token=refresh.token.get_secret_value(),
            not_before=refresh.not_before,
            expires_at=refresh.expires_at,
        )
        if refresh is not None
        else None
    )
    stored_resource = (
        StoredBrowserResource(
            audience=resource.audience,
            bearer=resource.bearer.get_secret_value(),
            expires_at=resource.expires_at,
        )
        if resource is not None
        else None
    )
    record = StoredBrowserSession(
        issuer=identity.issuer,
        subject=identity.subject,
        client_id=identity.client_id,
        expires_at=expires_at,
        session_expires_at=deadline,
    )
    if stored_refresh is not None:
        record.refresh = stored_refresh
    if stored_resource is not None:
        record.resource = stored_resource
    return PreparedBrowserSession(ticket, seconds, record, deadline)
