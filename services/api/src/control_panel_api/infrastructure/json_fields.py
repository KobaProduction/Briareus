"""Reject ambiguous JSON before a boundary's named schema decodes the document."""

import json


def _unique_members(pairs: list[tuple[str, object]]) -> tuple[tuple[str, object], ...]:
    names: set[str] = set()
    for name, _ in pairs:
        if name in names:
            raise ValueError("Duplicate JSON object member")
        names.add(name)
    return tuple(pairs)


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-JSON numeric constant: {value}")


def validate_unique_fields(raw: str | bytes | bytearray) -> None:
    """Validation only: neither mappings nor parser objects leave this boundary."""
    json.loads(raw, object_pairs_hook=_unique_members, parse_constant=_reject_constant)
