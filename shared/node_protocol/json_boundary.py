"""Unambiguous JSON-object validation followed by a concrete boundary model."""

import hashlib
import json
import math
from enum import Enum
from typing import Never

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from .control import canonical
from .domain.mcp_request import McpRequestFacts


class _ObjectMarker(Enum):
    OBJECT = "object"


def _unique_object(pairs: list[tuple[str, object]]) -> _ObjectMarker:
    names: set[str] = set()
    for name, _ in pairs:
        if name in names:
            raise ValueError("Duplicate JSON key")
        names.add(name)
    # This pass validates structure only. No generic document leaves it.
    return _ObjectMarker.OBJECT


def _invalid_constant(_value: str) -> Never:
    raise ValueError("Non-finite JSON value")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


class _McpDocumentInspector:
    """Retain validation state only, never a generic JSON document."""

    def __init__(self) -> None:
        self.unicode_scalars = True

    def _inspect_scalar(self, value: object) -> None:
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                self.unicode_scalars = False
        elif isinstance(value, list):
            for child in value:
                self._inspect_scalar(child)

    def object_members(self, pairs: list[tuple[str, object]]) -> _ObjectMarker:
        kind = _unique_object(pairs)
        for key, value in pairs:
            self._inspect_scalar(key)
            self._inspect_scalar(value)
        return kind


def mcp_json_is_object(raw: bytes | bytearray) -> bool:
    """Strict UTF-8 MCP preflight; the caller retains the untouched wire bytes."""
    inspector = _McpDocumentInspector()
    kind: object = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=inspector.object_members,
        parse_constant=_invalid_constant,
        parse_float=_finite_float,
    )
    if kind is not _ObjectMarker.OBJECT:
        return False
    if not inspector.unicode_scalars:
        raise ValueError("JSON strings must contain Unicode scalar values")
    return True


def require_json_object(raw: bytes | bytearray | str) -> None:
    try:
        kind: object = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
        if kind is not _ObjectMarker.OBJECT:
            raise ValueError("JSON object required")
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("Invalid bounded JSON object") from None


def decode_json[T: BaseModel](raw: bytes | bytearray | str, model: type[T]) -> T:
    require_json_object(raw)
    return model.model_validate_json(raw)


def request_facts(method: str, tool: str | None, arguments: object) -> McpRequestFacts:
    """Consume the parsed wire object without retaining it as an application contract."""
    if not isinstance(arguments, dict):
        raise ValueError("MCP arguments must be an object")
    original = arguments.get("tool")
    return McpRequestFacts(
        method,
        tool,
        hashlib.sha256(canonical(arguments)).hexdigest(),
        original if isinstance(original, str) else None,
    )


class McpRequestIdentity(BaseModel):
    """Only request identity is read; tool arguments remain on the execution plane."""

    model_config = ConfigDict(extra="ignore", strict=True)
    method: StrictStr | None = None
    id: StrictStr | StrictInt | None = None


def request_identity(raw: bytes) -> McpRequestIdentity:
    require_json_object(raw)
    # Keep Python JSON integer semantics for opaque caller selectors.
    return McpRequestIdentity.model_validate(json.loads(raw))
