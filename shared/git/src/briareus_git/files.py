"""Shared file encoding contract for source-control providers."""

from __future__ import annotations

import base64
import hashlib
from typing import Literal, Protocol

from briareus_json_values import JsonObject

FileEncoding = Literal["utf-8", "base64"]


class RepositoryFileProvider(Protocol):
    """Provider implementations retain their native metadata and write guards."""

    def get_file(
        self, repository: str, path: str, ref: str | None, encoding: FileEncoding, /
    ) -> JsonObject: ...

    def put_file(
        self,
        repository: str,
        path: str,
        content: str,
        message: str,
        branch: str,
        encoding: FileEncoding,
        /,
    ) -> JsonObject: ...


def encode_content(content: str, encoding: FileEncoding) -> str:
    """Return canonical base64 for provider APIs without changing binary bytes."""
    if encoding == "base64":
        base64.b64decode(content, validate=True)
        return content
    return base64.b64encode(content.encode("utf-8")).decode("ascii")


def content_fields(data: bytes, encoding: FileEncoding) -> JsonObject:
    if encoding == "base64":
        return {"content_base64": base64.b64encode(data).decode("ascii")}
    return {"content": data.decode("utf-8", "replace")}


def binary_result(data: bytes) -> JsonObject:
    return {
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        **content_fields(data, "base64"),
    }
