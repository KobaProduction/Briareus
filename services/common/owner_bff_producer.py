"""Compose original owner SQL/C2 observation and the existing Ed25519 BFF wire."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from functools import partial
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretStr

from common.application.owner_bff import CurrentOriginalGrant, ObserveOriginalOwnerStatus
from common.application.owner_bff import TrustedOriginalBffGrantPort as TrustedOriginalBffGrantPort
from common.domain.owner_bff import BffOwner, OriginalBffSelector
from common.domain.owner_bff import CurrentOriginalBffSourceGrant as CurrentOriginalBffSourceGrant
from common.infrastructure.owner_bff_ledger import SOURCE_DATABASES, SqlOriginalOwnerLedger
from common.owner_bff_signed import OriginalOwnerSignedEnvelope, SignedOriginalOwnerStatus
from common.platform_db import PlatformDatabase

_SOURCE_ISSUER: dict[BffOwner, str] = {
    "identity": "briareus-identity",
    "access": "briareus-access",
    "control": "briareus-platform",
    "catalog": "briareus-resources",
}


_utc_now = partial(datetime.now, UTC)


class BffOriginalOwnerSigner:
    def __init__(
        self,
        *,
        owner: BffOwner,
        db: PlatformDatabase,
        private_key_pem: SecretStr,
        grants: TrustedOriginalBffGrantPort,
    ) -> None:
        if db.engine.url.database != SOURCE_DATABASES[owner] or grants is None:
            raise RuntimeError("BFF signer must use the originating owner SQL and live C2")
        try:
            signing = serialization.load_pem_private_key(
                private_key_pem.get_secret_value().encode(),
                password=None,
            )
            if not isinstance(signing, Ed25519PrivateKey):
                raise ValueError("BFF source signer is not Ed25519")
        except (ValueError, TypeError):
            raise ValueError("invalid release-custodied BFF source signer key") from None
        self.owner, self.db, self.grants, self.key = owner, db, grants, signing
        self.kid = hashlib.sha256(
            signing.public_key().public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            )
        ).hexdigest()
        self._observe = ObserveOriginalOwnerStatus(
            SqlOriginalOwnerLedger(owner, db), CurrentOriginalGrant(grants, _utc_now), _utc_now
        )

    async def sign_original(
        self,
        *,
        actor_user_id: UUID,
        operation_uuid: UUID,
        original_key: str,
        original_operation: str,
        scope_sha256: str,
        binding_sha256: str,
        recipient_service_id: UUID,
        recipient_instance_uuid: UUID,
        source_evidence: object,
    ) -> OriginalOwnerSignedEnvelope:
        selector = OriginalBffSelector(
            self.owner,
            actor_user_id,
            operation_uuid,
            original_key,
            original_operation,
            scope_sha256,
            binding_sha256,
            recipient_service_id,
            recipient_instance_uuid,
        )
        fact = await self._observe.execute(selector, source_evidence)
        receipt = SignedOriginalOwnerStatus(
            owner=self.owner,
            actor_user_id=actor_user_id,
            operation_uuid=operation_uuid,
            original_idempotency_key_sha256=fact.original_idempotency_key_sha256,
            scope_sha256=scope_sha256,
            binding_sha256=binding_sha256,
            owner_revision=fact.owner_revision,
            phase=fact.phase,
            issued_at=fact.issued_at,
            expires_at=fact.expires_at,
            recipient_service_id=recipient_service_id,
            recipient_instance_uuid=recipient_instance_uuid,
        )
        jws = jwt.encode(
            {
                "iss": _SOURCE_ISSUER[self.owner],
                "aud": f"briareus:admin-bff:{recipient_service_id}",
                "iat": int(fact.issued_at.timestamp()),
                "nbf": int(fact.issued_at.timestamp()),
                "exp": int(fact.expires_at.timestamp()),
                "jti": str(uuid4()),
                "purpose": "briareus-bff-original-owner-v1",
                "receipt": receipt.model_dump(mode="json"),
            },
            self.key,
            algorithm="EdDSA",
            headers={"typ": "briareus-bff-owner+jwt", "kid": self.kid},
        )
        return OriginalOwnerSignedEnvelope(receipt=receipt, attestation_jws=jws)
