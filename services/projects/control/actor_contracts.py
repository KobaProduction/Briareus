"""Existing Platform actor fact and verification port shared by its source layouts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from common.owner_contracts import VerifiedOwnerServicePeer


@dataclass(frozen=True, slots=True)
class VerifiedControlActor:
    """Already verified by current Identity issuer; never a request body."""

    user_id: UUID
    role: Literal["user", "superuser"]
    credential_version: int
    recipient_service_id: UUID
    expires_at: datetime


class TrustedControlActorSource(Protocol):
    def verify_actor(
        self, evidence: object, *, service_peer: VerifiedOwnerServicePeer
    ) -> VerifiedControlActor:
        """Must verify fresh signed Identity proof and original delegation."""
        ...
