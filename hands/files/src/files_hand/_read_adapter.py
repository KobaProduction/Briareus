"""Bounded Files read arguments and verified-content DTOs.

Native read adapters consume these shapes; this module performs no I/O and
does not issue grants, owner evidence or signed read receipts.
"""

from __future__ import annotations

import base64
import hashlib
import unicodedata
from dataclasses import dataclass, field

from modules.files.a6_signed import A6FilesUnavailable, canonical_files_path
from modules.project_runtime import ProjectFileError

_MAX_READ_BYTES = 262_144
_MAX_RELATIVE_PATH_BYTES = 4096


class FilesMcpReadUnavailable(Exception):
    """Public failure code only; never an owner error or filesystem path."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class FilesReadArguments:
    """Only a relative file path and a bounded byte budget are caller input."""

    path: str
    max_bytes: int

    def __post_init__(self) -> None:
        # A direct internal constructor must enforce the same contract as
        # untrusted JSON parsing. This also keeps output encoding bounded.
        if not isinstance(self.path, str):
            raise FilesMcpReadUnavailable("FILES_READ_ARGUMENTS_INVALID")
        if (
            not 1 <= len(self.path) <= _MAX_RELATIVE_PATH_BYTES
            or not unicodedata.is_normalized("NFC", self.path)
            or type(self.max_bytes) is not int
            or (not 1 <= self.max_bytes <= _MAX_READ_BYTES)
        ):
            raise FilesMcpReadUnavailable("FILES_READ_ARGUMENTS_INVALID")
        try:
            canonical = canonical_files_path(self.path)
            if canonical != self.path:
                raise ValueError("noncanonical file path")
        except (ProjectFileError, A6FilesUnavailable, ValueError, UnicodeError):
            raise FilesMcpReadUnavailable("FILES_READ_PATH_INVALID") from None

    @classmethod
    def parse(cls, arguments: object) -> FilesReadArguments:
        if not isinstance(arguments, dict):
            raise FilesMcpReadUnavailable("FILES_READ_ARGUMENTS_INVALID")
        if set(arguments) not in ({"path"}, {"path", "max_bytes"}):
            raise FilesMcpReadUnavailable("FILES_READ_ARGUMENTS_INVALID")
        return cls(path=arguments["path"], max_bytes=arguments.get("max_bytes", _MAX_READ_BYTES))

    def canonical_arguments(self) -> FilesReadArguments:
        """Defaults and path are already frozen and validated."""
        return self


@dataclass(frozen=True, slots=True)
class FilesReadContent:
    """Only bounded verified bytes become an MCP JSON-safe response.

    This structure is NOT a grant, owner evidence, read witness or signed
    receipt. It must be constructed only AFTER the owner read completes.
    """

    path: str
    size_bytes: int
    sha256: str
    content_base64: str = field(repr=False)

    def content_payload(self) -> FilesReadContent:
        """Verified content remains typed until the outer SDK serializer."""
        return self

    @classmethod
    def from_verified_bytes(cls, request: FilesReadArguments, payload: bytes) -> FilesReadContent:
        if not isinstance(request, FilesReadArguments):
            raise FilesMcpReadUnavailable("FILES_READ_RESULT_INVALID")
        if type(payload) is not bytes or len(payload) > request.max_bytes:
            raise FilesMcpReadUnavailable("FILES_READ_RESULT_INVALID")
        return cls(
            path=request.path,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            content_base64=base64.b64encode(payload).decode("ascii"),
        )
