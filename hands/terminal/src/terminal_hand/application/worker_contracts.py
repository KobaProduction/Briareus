"""A Terminal operation returns an existing typed receipt or a bounded failure."""

from dataclasses import dataclass

from runtime_peer.terminal_receipts import TerminalReceipt


@dataclass(frozen=True)
class WorkerOutcome:
    result: TerminalReceipt | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if (self.result is None) == (self.error is None):
            raise ValueError("Exactly one worker outcome is required")
