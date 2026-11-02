"""Durable receipts distinguish a new effect from an outcome replay."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DispatchIdentity:
    operation: UUID
    fingerprint: str


@dataclass(frozen=True, slots=True)
class DispatchReservation[Outcome]:
    replay: bool
    outcome: Outcome


def require_same_effect(expected: str, observed: str) -> None:
    if expected != observed:
        raise ValueError("Browser operation identity reused")


def require_history_capacity(count: int) -> None:
    if count >= 10000:
        raise ValueError("Browser operation history capacity exceeded")
