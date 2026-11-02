"""Compatibility API for the canonical shared Files client implementation."""

import asyncio as asyncio
import hashlib as hashlib
import json as json
import math as math
import re as re
from contextlib import suppress as suppress
from dataclasses import dataclass as dataclass
from datetime import UTC as UTC
from datetime import datetime as datetime
from datetime import timedelta as timedelta
from typing import Literal as Literal
from typing import NoReturn as NoReturn
from typing import Protocol as Protocol
from uuid import UUID as UUID

from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pydantic import Field as Field
from pydantic import field_validator as field_validator

from modules.project_runtime import ProjectInvocation as ProjectInvocation
from modules.project_runtime import ProjectPermit as ProjectPermit
from modules.project_runtime import ProjectRuntimeAuthority as ProjectRuntimeAuthority
from modules.project_runtime.authorization import valid_project_revision as valid_project_revision
from modules.project_runtime.owner_effects import OwnerEffectClient as OwnerEffectClient
from modules.project_runtime.owner_effects import OwnerEffectUnavailable as OwnerEffectUnavailable
from project_runtime_client.files.signed import _FILE_STATE as _FILE_STATE
from project_runtime_client.files.signed import _SHA as _SHA
from project_runtime_client.files.signed import A6FilesUnavailable as A6FilesUnavailable
from project_runtime_client.files.signed import AttestedFilesStorage as AttestedFilesStorage
from project_runtime_client.files.signed import FilesCommand as FilesCommand
from project_runtime_client.files.signed import (
    FilesCommittedObservation as FilesCommittedObservation,
)
from project_runtime_client.files.signed import FilesInspect as FilesInspect
from project_runtime_client.files.signed import FilesQuotaReceipt as FilesQuotaReceipt
from project_runtime_client.files.signed import FilesRead as FilesRead
from project_runtime_client.files.signed import FilesReadPermit as FilesReadPermit
from project_runtime_client.files.signed import FilesReserve as FilesReserve
from project_runtime_client.files.signed import FilesSignedIntent as FilesSignedIntent
from project_runtime_client.files.signed import FilesTransition as FilesTransition
from project_runtime_client.files.signed import SignedFilesBackendPort as SignedFilesBackendPort
from project_runtime_client.files.signed import TrustedFilesStoragePort as TrustedFilesStoragePort
from project_runtime_client.files.signed import VerifiedFilesPeer as VerifiedFilesPeer
from project_runtime_client.files.signed import VerifiedFilesPeerPort as VerifiedFilesPeerPort
from project_runtime_client.files.signed import (
    _AssertionDependencySignedFilesFlow as _SharedA6SignedFilesFlow,
)
from project_runtime_client.files.signed import _reconciliation_absent as _reconciliation_absent
from project_runtime_client.files.signed import (
    _require_peer_identifiers as _require_peer_identifiers,
)
from project_runtime_client.files.signed import canonical_files_path as canonical_files_path
from project_runtime_client.files.signed import (
    files_payload_fingerprint as files_payload_fingerprint,
)
from project_runtime_client.files.signed import path_fingerprint as path_fingerprint

from .project_workspace import _components as _components


class A6SignedFilesFlow(_SharedA6SignedFilesFlow[OwnerEffectClient]):
    """Keep the local flow type and exact nominal signed-ledger fence."""

    _owner_effect_client_type = OwnerEffectClient
