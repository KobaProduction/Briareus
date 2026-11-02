"""Untrusted binary bytes have bounded names, exact integrity, and canonical opaque handles."""

import base64
import hashlib
import re
from dataclasses import dataclass
from uuid import UUID

MAX_BINARY = 16 * 1024**2
MAX_CHUNK = 12 * 1024
MAX_STORAGE = 128 * 1024**2
MAX_OUTPUT = 900_000
MAX_ENTRIES = 64
R2_VERSION = "6.2.4"


def identifier(value: str) -> UUID:
    parsed = UUID(value)
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("Canonical binary/upload UUID required")
    return parsed


def require_identifier(value: UUID) -> UUID:
    if not isinstance(value, UUID):
        raise ValueError("Canonical binary/upload UUID required")
    if value.version != 4:
        raise ValueError("Canonical binary/upload UUID required")
    return value


def address(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("A hexadecimal numeric address is required")
    if not re.fullmatch(r"0x[0-9a-fA-F]{1,16}", value):
        raise ValueError("A hexadecimal numeric address is required")
    return hex(int(value, 16))


def bounded_int(value: int, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Numeric parameter is outside its permitted range")
    return value


def decode_chunk(value: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError("A bounded base64 chunk is required")
    if not 0 < len(value) <= 4 * ((MAX_CHUNK + 2) // 3):
        raise ValueError("A bounded base64 chunk is required")
    decoded = base64.b64decode(value, validate=True)
    if not 0 < len(decoded) <= MAX_CHUNK:
        raise ValueError("Invalid binary chunk length")
    return decoded


@dataclass(frozen=True, slots=True)
class BinaryManifest:
    name: str
    sha256: str
    size: int
    created_at: int

    def require_upload(self) -> None:
        if (
            not self.name
            or len(self.name) > 128
            or any(ord(char) < 32 for char in self.name)
            or "/" in self.name
            or "\\" in self.name
        ):
            raise ValueError("A printable binary display name is required")
        if not re.fullmatch(r"[a-f0-9]{64}", self.sha256):
            raise ValueError("An exact SHA256 digest is required")
        bounded_int(self.size, 1, MAX_BINARY)

    def require_integrity(self, data: bytes, *, stored: bool = False) -> None:
        if len(data) != self.size or hashlib.sha256(data).hexdigest() != self.sha256:
            message = (
                "Stored binary integrity check failed"
                if stored
                else "Upload length or SHA256 does not match"
            )
            raise ValueError(message)


def require_capacity(manifests: tuple[BinaryManifest, ...], size: int) -> None:
    if len(manifests) >= MAX_ENTRIES or sum(item.size for item in manifests) + size > MAX_STORAGE:
        raise ValueError("Private analysis storage capacity reached")


def require_chunk(metadata: BinaryManifest, *, offset: int, length: int) -> None:
    if offset + length > metadata.size:
        raise ValueError("Chunk exceeds declared binary length")
