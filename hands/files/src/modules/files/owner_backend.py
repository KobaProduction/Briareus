"""Compatibility API for the canonical shared Files client implementation."""

import hashlib as hashlib
from typing import Literal as Literal

from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict

from modules.project_runtime import ProjectInvocation as ProjectInvocation
from modules.project_runtime.owner_effects import OwnerEffectClient as OwnerEffectClient
from modules.project_runtime.owner_effects import OwnerEffectReply as OwnerEffectReply
from modules.project_runtime.owner_effects import OwnerEffectUnavailable as OwnerEffectUnavailable
from project_runtime_client.files.owner_backend import FilesOwnerInspection as FilesOwnerInspection
from project_runtime_client.files.owner_backend import (
    _CompositionFilesOwnerBackend as _SharedFilesOwnerBackend,
)

from .a6_signed import _FILE_STATE as _FILE_STATE
from .a6_signed import FilesCommittedObservation as FilesCommittedObservation
from .a6_signed import FilesInspect as FilesInspect
from .a6_signed import FilesQuotaReceipt as FilesQuotaReceipt
from .a6_signed import FilesRead as FilesRead
from .a6_signed import FilesReadPermit as FilesReadPermit
from .a6_signed import FilesReserve as FilesReserve
from .a6_signed import FilesSignedIntent as FilesSignedIntent
from .a6_signed import FilesTransition as FilesTransition
from .a6_signed import VerifiedFilesPeer as VerifiedFilesPeer
from .a6_signed import files_payload_fingerprint as files_payload_fingerprint
from .a6_signed import path_fingerprint as path_fingerprint


class FilesOwnerBackend(_SharedFilesOwnerBackend[OwnerEffectClient]):
    """Keep the exact local signed-effects constructor fence."""

    _owner_effect_client_type = OwnerEffectClient
