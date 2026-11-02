"""Exact private-PDP acknowledgement, including duplicate-key rejection."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AuthorizationAllowed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    allowed: Literal[True]


def _allowed_pairs(pairs: list[tuple[str, object]]) -> AuthorizationAllowed:
    # The one-field contract also rejects repeated keys and nested objects.
    if len(pairs) != 1 or pairs[0][0] != "allowed" or pairs[0][1] is not True:
        raise ValueError("Invalid or ambiguous Authorization acknowledgement")
    return AuthorizationAllowed(allowed=True)


def decode_allowed(body: bytes) -> AuthorizationAllowed:
    value: object = json.loads(body, object_pairs_hook=_allowed_pairs)
    if not isinstance(value, AuthorizationAllowed):
        raise ValueError("Authorization acknowledgement must be an object")
    return value
