"""Owner-local compatibility and codec boundary for shared runtime clients."""

from __future__ import annotations

import asyncio as asyncio
import hashlib as hashlib
import json as json
import math as math
from dataclasses import dataclass as dataclass
from datetime import UTC as UTC
from datetime import datetime as datetime
from typing import TYPE_CHECKING
from typing import Literal as Literal
from typing import Protocol as Protocol
from uuid import UUID as UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as Ed25519PublicKey
from pydantic import BaseModel as BaseModel

from common.domain.owner_authority import OwnerAuthorityUnavailable as OwnerAuthorityUnavailable
from common.owner_effect_phase_map import (
    require_exact_owner_operation as require_exact_owner_operation,
)
from project_runtime_client.owner_effects import OwnerEffectBackendPort as OwnerEffectBackendPort
from project_runtime_client.owner_effects import OwnerEffectReply as OwnerEffectReply
from project_runtime_client.owner_effects import OwnerEffectTrustPort as OwnerEffectTrustPort
from project_runtime_client.owner_effects import (
    _CompatibilityOwnerEffectClient as _SharedOwnerEffectClient,
)
from project_runtime_client.owner_effects import _digest as _digest

from .a11_owner_wire import A11OwnerCommandDTO as A11OwnerCommandDTO
from .a11_owner_wire import A11TargetOwner as A11TargetOwner
from .a11_owner_wire import VerifiedA11RevisionPort as VerifiedA11RevisionPort
from .authorization import ProjectAccessDenied as ProjectAccessDenied
from .authorization import ProjectAction as ProjectAction
from .authorization import ProjectInvocation as ProjectInvocation
from .authorization import ProjectPermit as ProjectPermit
from .authorization import ProjectRuntimeAuthority as ProjectRuntimeAuthority
from .domain.effect_admission import EffectAdmission as EffectAdmission
from .domain.effect_identity import OriginalEffectIdentity as OriginalEffectIdentity
from .domain.effect_protocol import _A11_TARGET as _A11_TARGET
from .domain.effect_protocol import _DB as _DB
from .domain.effect_protocol import EffectOwner as EffectOwner
from .domain.effect_protocol import EffectPhase as EffectPhase
from .domain.effect_receipt import OwnerEffectUnavailable as OwnerEffectUnavailable
from .domain.effect_receipt import ReceiptExpectation as ReceiptExpectation
from .domain.identifiers import valid_uuid as valid_uuid
from .domain.source_proof import SourceProofMismatch as SourceProofMismatch
from .infrastructure.effect_contracts import OwnerEffectCommand as OwnerEffectCommand
from .infrastructure.effect_contracts import OwnerEffectReceipt as OwnerEffectReceipt
from .infrastructure.effect_contracts import OwnerFenceDTO as OwnerFenceDTO
from .infrastructure.effect_contracts import SignedOwnerEffectReceipt as SignedOwnerEffectReceipt
from .infrastructure.effect_dispatch import EffectDispatch as EffectDispatch
from .infrastructure.effect_dispatch import dispatch_effect as dispatch_effect
from .infrastructure.effect_receipt import command_binding as command_binding
from .infrastructure.effect_receipt import receipt_observation as receipt_observation
from .infrastructure.effect_receipt import verify_attestation as verify_attestation
from .infrastructure.owner_payloads import OwnerBusinessPayload as OwnerBusinessPayload
from .infrastructure.payload_identity import payload_effect_identity as payload_effect_identity
from .infrastructure.source_proof import dispatch_requirement as dispatch_requirement
from .infrastructure.source_proof import source_proof as source_proof
from .infrastructure.source_proof import status_requirement as status_requirement
from .owner_authorization import VerifiedOwnerRecipient as VerifiedOwnerRecipient
from .owner_wire import A11OwnerWireNotAccepted as A11OwnerWireNotAccepted
from .owner_wire import accepted_a11_owner_wire as accepted_a11_owner_wire
from .owner_wire import require_accepted_owner_lifecycle as require_accepted_owner_lifecycle

if TYPE_CHECKING:
    from modules.analysis.a6_native import (
        NativeImportClaimCommand,
        NativeImportInspect,
        NativeImportTransition,
    )
    from modules.files.a6_signed import (
        FilesCommittedObservation,
        FilesInspect,
        FilesRead,
        FilesReserve,
        FilesTransition,
    )
    from project_runtime_client.a6_provider import ProviderReadCommand
    from project_runtime_client.a6_runtime import (
        RuntimeJobCommand,
        RuntimeLeaseCommand,
        RuntimeOpenCommand,
    )
    from project_runtime_client.catalog_owner import CatalogListRequest, CatalogResolveRequest

    type OwnerEffectPayload = (
        NativeImportClaimCommand
        | NativeImportInspect
        | NativeImportTransition
        | FilesCommittedObservation
        | FilesInspect
        | FilesRead
        | FilesReserve
        | FilesTransition
        | CatalogListRequest
        | CatalogResolveRequest
        | ProviderReadCommand
        | RuntimeJobCommand
        | RuntimeLeaseCommand
        | RuntimeOpenCommand
    )


class OwnerEffectClient(_SharedOwnerEffectClient["OwnerEffectPayload"]):
    """Keep this root's nominal sender type and payload contract."""
