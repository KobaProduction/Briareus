"""Observed OAuth scope storage retains its existing JSON and item coercion."""

import json
from typing import Annotated

from pydantic import BeforeValidator, TypeAdapter, ValidationError

_SCOPES: TypeAdapter[list[str]] = TypeAdapter(list[Annotated[str, BeforeValidator(str)]])


def decode_observed_scopes(raw: str) -> list[str]:
    try:
        return _SCOPES.validate_python(json.loads(raw), strict=True)
    except (json.JSONDecodeError, ValidationError):
        return []


def encode_observed_scopes(scopes: list[str]) -> str:
    return json.dumps(scopes, ensure_ascii=False)
