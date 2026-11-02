"""Exact source-owned signed Access command parameters; no coercion or defaults."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionRevocationPayload:
    """Revocation signs the original empty business body."""


@dataclass(frozen=True, slots=True)
class ElevationResolutionPayload:
    approval_id: str
    approve: bool
    allowed_grants: list[str] | None
    explicit_expansion_confirmation: bool
    expected_approval_version: int
