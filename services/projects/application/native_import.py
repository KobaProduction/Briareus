"""Trusted signed Files and native-effect observation ports for Reverse imports."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from common.owner_contracts import VerifiedOwnerServicePeer
from projects.domain.native_import import (
    VerifiedFilesSourceReceipt,
    VerifiedNativeImportObservation,
)


class TrustedFilesSourcePort(Protocol):
    def verify_current_file(
        self, evidence: object, *, project_id: UUID, file_object_id: UUID
    ) -> VerifiedFilesSourceReceipt:
        """Must independently validate signed Files owner revision/provenance."""
        ...


class TrustedNativeImportObserver(Protocol):
    def verify_native_effect(
        self, evidence: object, *, peer: VerifiedOwnerServicePeer
    ) -> VerifiedNativeImportObservation:
        """Must verify signed Ghidra/OS provenance, not a caller UUID/path."""
        ...
