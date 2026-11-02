"""Typed private Project commands and effect results; never public MCP schemas."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FileList:
    path: str
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class FilePath:
    path: str


@dataclass(frozen=True, slots=True)
class FileRead:
    path: str
    max_bytes: int


@dataclass(frozen=True, slots=True)
class FileUpload:
    destination: str
    operation_uuid: UUID
    size_bytes: int
    sha256: str
    content_base64: str


@dataclass(frozen=True, slots=True)
class FileWriteStatus:
    operation_uuid: UUID
    destination: str


ResourceScope = Literal["all", "project", "team"]
ResourceProvider = Literal["github", "gitlab", "coolify", "signoz"]


@dataclass(frozen=True, slots=True)
class ResourceSelection:
    scope: ResourceScope
    owner_id: UUID | None
    provider: Literal["coolify", "signoz"] | None = None


ProjectCommand = FileList | FilePath | FileRead | FileUpload | FileWriteStatus | ResourceSelection


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: str
    kind: str
    size_bytes: int
    modified_at_ns: int


@dataclass(frozen=True, slots=True)
class FilePage:
    entries: tuple[FileEntry, ...]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class FileDigest:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class FileContents:
    path: str
    data: str
    size_bytes: int
    sha256: str
    encoding: Literal["base64"] = "base64"


@dataclass(frozen=True, slots=True)
class FileCommitted:
    operation_uuid: UUID
    path: str
    size_bytes: int
    sha256: str
    kind: Literal["file"] = "file"
    status: Literal["committed"] = "committed"


@dataclass(frozen=True, slots=True)
class FileUnverified:
    operation_uuid: UUID
    found: Literal[False] = False
    retry_allowed: Literal[False] = False
    outcome: Literal["unverified"] = "unverified"


@dataclass(frozen=True, slots=True)
class FileWriteObservation:
    operation_uuid: UUID
    outcome: str
    ledger_revision: int
    planned_bytes: int
    expires_at: datetime
    disk_observation_required: bool
    found: Literal[True] = True
    retry_allowed: Literal[False] = False


@dataclass(frozen=True, slots=True)
class WriteLedgerState:
    status: str
    reservation_version: int
    requested_bytes: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IntegrationMetadata:
    resource_id: UUID
    name: str
    provider: str
    auth_type: str
    owner_scope: str
    owner_id: UUID
    inherited: bool
    resource_version: int


@dataclass(frozen=True, slots=True)
class VariableMetadata:
    resource_id: UUID
    name: str
    kind: str
    owner_scope: str
    owner_id: UUID
    inherited: bool
    resource_version: int
    masked: Literal[True] = True


@dataclass(frozen=True, slots=True)
class IntegrationCatalog:
    resources: tuple[IntegrationMetadata, ...]


@dataclass(frozen=True, slots=True)
class VariableCatalog:
    resources: tuple[VariableMetadata, ...]


ProjectResult = (
    FilePage
    | FileEntry
    | FileDigest
    | FileContents
    | FileCommitted
    | FileUnverified
    | FileWriteObservation
    | IntegrationCatalog
    | VariableCatalog
)
