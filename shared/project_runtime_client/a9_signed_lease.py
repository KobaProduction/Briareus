"""Independent A9 ledger attestation boundary; no OS cleanup is inferred."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ValidationError

from .authorization import ProjectPermit
from .domain.runtime_lease import A9SignedLeaseUntrusted as A9SignedLeaseUntrusted
from .domain.runtime_lease import RuntimeLeaseExpectation, RuntimeLeaseScope
from .infrastructure.lease_contracts import (
    RuntimeLeaseReceipt as RuntimeLeaseReceipt,
)
from .infrastructure.lease_contracts import (
    SignedRuntimeLeaseReceipt as SignedRuntimeLeaseReceipt,
)
from .infrastructure.runtime_lease import runtime_lease_snapshot, verify_runtime_lease_token


class A9PinnedRuntimeKeyPort(Protocol):
    """Resolve one operator-approved A9 signing key from actual C2 trust.

    Never accept a key supplied by an MCP tool, client/header, unsigned JWS
    `kid`, arbitrary HTTP/JWKS URL, or Backend response body. The private
    signing key never exists in this Runtime process.
    """

    async def pinned_backend_lease_key(
        self,
        *,
        expected_service_id: UUID,
        expected_instance_uuid: UUID,
    ) -> Ed25519PublicKey: ...


def verify_a9_signed_lease(
    response: SignedRuntimeLeaseReceipt,
    *,
    trusted_public_key: Ed25519PublicKey,
    expected_service_id: UUID,
    expected_instance_uuid: UUID,
    expected_audience: Literal["files", "terminal", "web", "reverse"],
    permit: ProjectPermit,
    expected_runtime_session_uuid: UUID,
    expected_kind: Literal["files", "terminal", "web_managed", "web_remote", "reverse"],
) -> RuntimeLeaseReceipt:
    """Verify the pinned token and original scope, freshness and takeover rules."""
    if not isinstance(response, SignedRuntimeLeaseReceipt):
        raise A9SignedLeaseUntrusted("A9_LEASE_TRUSTED_EXPECTATIONS_INVALID")
    if not isinstance(trusted_public_key, Ed25519PublicKey):
        raise A9SignedLeaseUntrusted("A9_LEASE_TRUSTED_EXPECTATIONS_INVALID")
    expected = RuntimeLeaseExpectation(
        RuntimeLeaseScope(
            permit.project_id,
            permit.session_uuid,
            permit.actor_id,
            expected_service_id,
            expected_runtime_session_uuid,
            expected_kind,
        ),
        expected_instance_uuid,
        expected_audience,
        permit.decision_version,
        permit.project_access_revision,
        permit.expires_at,
    )
    expected.require_trusted(datetime.now(UTC))
    try:
        verified = verify_runtime_lease_token(
            response,
            key=trusted_public_key,
            expected=expected,
        )
        runtime_lease_snapshot(verified.receipt).require_for(
            expected,
            attestation_expires_at=response.attestation_expires_at,
            token_expires_at=verified.claims.expires_at,
            now=datetime.now(UTC),
        )
        return verified.receipt
    except A9SignedLeaseUntrusted:
        raise
    except (
        jwt.PyJWTError,
        ValidationError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    ) as exc:
        raise A9SignedLeaseUntrusted("A9_LEASE_ATTESTATION_INVALID") from exc
