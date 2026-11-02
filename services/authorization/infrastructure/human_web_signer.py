"""Encode the exact human authority into the existing short Node evidence."""

from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from authorization.domain.human_web import HumanLease
from node_protocol.effect import HumanEffectPermit, sign_permit


@dataclass(frozen=True, slots=True)
class HumanEffectSigner:
    key: Ed25519PrivateKey

    @property
    def public_key(self) -> str:
        return (
            self.key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        )

    def sign(self, lease: HumanLease) -> str:
        call, binding = lease.call, lease.binding
        permit = HumanEffectPermit.model_validate(
            {
                "human": True,
                "module": call.module,
                "actor_uuid": lease.identity.actor_uuid,
                "project_uuid": call.project_uuid,
                "node_uuid": binding.node_uuid,
                "placement_uuid": binding.placement_uuid,
                "workspace_uuid": binding.workspace_uuid,
                "request_uuid": call.request_uuid,
                "resource_id": binding.resource_id,
                "resource_revision": binding.resource_revision,
                "fingerprint": binding.fingerprint,
                "body_digest": call.body_digest,
                "bearer_digest": call.bearer_digest,
                "arguments_digest": call.arguments_digest,
                "method": call.method,
                "tool": call.tool,
                "issued_at": lease.issued_at,
                "expires_at": lease.expires_at,
            }
        )
        return sign_permit(permit, self.key)
