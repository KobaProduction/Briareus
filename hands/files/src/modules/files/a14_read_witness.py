"""Compatibility API for the canonical shared Files client implementation."""

import asyncio as asyncio
from dataclasses import dataclass as dataclass
from datetime import UTC as UTC
from datetime import datetime as datetime
from datetime import timedelta as timedelta
from typing import Protocol as Protocol
from uuid import UUID as UUID

from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pydantic import Field as Field
from pydantic import model_validator as model_validator

from modules.project_runtime import ProjectAccessDenied as ProjectAccessDenied
from modules.project_runtime import ProjectInvocation as ProjectInvocation
from modules.project_runtime import ProjectPermit as ProjectPermit
from modules.project_runtime import ProjectRuntimeAuthority as ProjectRuntimeAuthority
from modules.project_runtime.owner_authorization import (
    VerifiedOwnerRecipient as VerifiedOwnerRecipient,
)
from modules.project_runtime.owner_effects import OwnerEffectClient as OwnerEffectClient
from modules.project_runtime.owner_effects import OwnerEffectUnavailable as OwnerEffectUnavailable
from project_runtime_client.files.read_witness import A14FilesReadPreflight as A14FilesReadPreflight
from project_runtime_client.files.read_witness import (
    CurrentCommittedFileObject as CurrentCommittedFileObject,
)
from project_runtime_client.files.read_witness import (
    CurrentCommittedFileSourcePort as CurrentCommittedFileSourcePort,
)
from project_runtime_client.files.read_witness import (
    FilesReadBusinessPreimage as FilesReadBusinessPreimage,
)
from project_runtime_client.files.read_witness import TrustedNativeReadPort as TrustedNativeReadPort
from project_runtime_client.files.read_witness import (
    VerifiedNativeFileReadObservation as VerifiedNativeFileReadObservation,
)
from project_runtime_client.files.read_witness import _original_operation as _original_operation
from project_runtime_client.files.read_witness import (
    _require_read_continuity as _require_read_continuity,
)
from project_runtime_client.files.read_witness import (
    _require_snapshot_current as _require_snapshot_current,
)
from project_runtime_client.files.read_witness import _require_witness as _require_witness
from project_runtime_client.files.read_witness import _v4 as _v4

from .a6_signed import canonical_files_path as canonical_files_path
from .a6_signed import path_fingerprint as path_fingerprint
from .domain.read_witness import FileContentBinding as FileContentBinding
from .domain.read_witness import NativeReadBinding as NativeReadBinding
from .domain.read_witness import ReadWitnessChanged as ReadWitnessChanged
from .domain.read_witness import ReadWitnessExpectation as ReadWitnessExpectation
from .domain.read_witness import ReadWitnessObservation as ReadWitnessObservation
from .domain.read_witness import require_current_witness as require_current_witness
from .infrastructure.read_payloads import FilesReadBusinessPayload as FilesReadBusinessPayload
from .infrastructure.read_payloads import (
    NativeReadBusinessObservation as NativeReadBusinessObservation,
)
from .project_workspace import ProjectFileSnapshot as ProjectFileSnapshot
