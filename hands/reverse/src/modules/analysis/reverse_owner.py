"""Compatibility exports for the shared Analysis client implementation."""

from __future__ import annotations

import hashlib as hashlib
from dataclasses import replace as replace
from datetime import UTC as UTC
from datetime import datetime as datetime
from typing import Literal as Literal
from typing import Protocol as Protocol
from uuid import UUID as UUID

from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pydantic import Field as Field

from modules.project_runtime import ProjectInvocation as ProjectInvocation
from modules.project_runtime import ProjectOperationScope as ProjectOperationScope
from modules.project_runtime import ProjectRuntimeAuthority as ProjectRuntimeAuthority
from modules.project_runtime import canonical_request_fingerprint as canonical_request_fingerprint
from modules.project_runtime.domain.identifiers import valid_uuid as valid_uuid
from modules.project_runtime.owner_effects import OwnerEffectClient as OwnerEffectClient
from modules.project_runtime.owner_effects import OwnerEffectUnavailable as OwnerEffectUnavailable
from project_runtime_client.analysis.reverse_owner import CommittedFileObject as CommittedFileObject
from project_runtime_client.analysis.reverse_owner import (
    CommittedFileObjectLookup as CommittedFileObjectLookup,
)
from project_runtime_client.analysis.reverse_owner import FileObjectRevision as FileObjectRevision
from project_runtime_client.analysis.reverse_owner import (
    NativeOSInventoryPort as NativeOSInventoryPort,
)
from project_runtime_client.analysis.reverse_owner import ReverseInspection as ReverseInspection
from project_runtime_client.analysis.reverse_owner import ReverseOwnerClient as ReverseOwnerClient
from project_runtime_client.analysis.reverse_owner import (
    ReverseReconcileCommand as ReverseReconcileCommand,
)
from project_runtime_client.analysis.reverse_owner import (
    VerifiedNativeInventory as VerifiedNativeInventory,
)
from project_runtime_client.analysis.reverse_owner import native_digest as native_digest
from project_runtime_client.analysis.reverse_owner import object_digest as object_digest

from .a6_native import NativeImportClaimCommand as NativeImportClaimCommand
from .a6_native import NativeImportInspect as NativeImportInspect
from .a6_native import NativeImportReceipt as NativeImportReceipt
from .a6_native import NativeImportTransition as NativeImportTransition
