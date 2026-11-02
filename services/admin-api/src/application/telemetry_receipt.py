"""Result of local telemetry admission, not collector durability."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TelemetryEnqueueReceipt:
    accepted: int
    queued_batches: int
    dropped_batches: int
