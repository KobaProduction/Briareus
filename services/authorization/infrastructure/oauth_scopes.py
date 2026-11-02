"""Preserve the stored JSON iterable and the pinned SDK string-item validation."""

import json
from typing import Annotated

from pydantic import BeforeValidator, TypeAdapter

_SCOPES: TypeAdapter[list[str]] = TypeAdapter(Annotated[list[str], BeforeValidator(list)])


def decode_scopes(raw: str) -> tuple[str, ...]:
    return tuple(_SCOPES.validate_python(json.loads(raw)))


def encode_scopes(scopes: list[str]) -> str:
    return json.dumps(scopes, separators=(",", ":"))
