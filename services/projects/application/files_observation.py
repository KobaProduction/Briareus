"""Trusted native observation verifier port for Files reconciliation."""

from __future__ import annotations

from typing import Protocol

from common.owner_contracts import VerifiedOwnerServicePeer
from projects.domain.files_observation import VerifiedNativeFilesObservation


class TrustedFilesObservationPort(Protocol):
    def verify_observation(
        self, evidence: object, *, peer: VerifiedOwnerServicePeer
    ) -> VerifiedNativeFilesObservation:
        """Must check actual OS-root evidence and signed original effect ID."""
        ...
