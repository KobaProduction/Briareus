"""Bounded external authority JSON decoding with duplicate-key rejection."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, init=False)
class AuthorityObject(Mapping[str, object]):
    """Immutable decoded JSON object that cannot represent duplicate keys.

    This is the external JSON decoder's object representation. Boundary models
    consume its mapping protocol; no application result carries raw documents.
    """

    _pairs: tuple[tuple[str, object], ...]

    def __init__(self, pairs: list[tuple[str, object]]) -> None:
        names = tuple(key for key, _ in pairs)
        if len(set(names)) != len(names):
            raise ValueError("private authority response has duplicate field")
        object.__setattr__(self, "_pairs", tuple(pairs))

    def __getitem__(self, key: str) -> object:
        for name, value in self._pairs:
            if name == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (name for name, _ in self._pairs)

    def __len__(self) -> int:
        return len(self._pairs)


def _reject_nonfinite(_value: str) -> object:
    raise ValueError("nonfinite number in private authority response")


def load_authority_json(body: bytes) -> object:
    """Parse bytes with one value per key at *every* JSON object depth.

    Callers already cap response lengths; no arbitrary URL/transport is
    selected by this utility and no IAM/User/Permit result is manufactured.
    """
    if not isinstance(body, bytes):
        raise ValueError("expected bounded response bytes")
    try:
        decoded: object = json.loads(
            body, object_pairs_hook=AuthorityObject, parse_constant=_reject_nonfinite
        )
        return decoded
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("invalid private authority JSON") from None
