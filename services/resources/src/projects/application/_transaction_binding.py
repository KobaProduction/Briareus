"""Typed transaction and clock references for existing Resources use cases."""

from collections.abc import Callable
from datetime import datetime


class _TransactionClockBinding[TransactionsT]:
    def __init__(self, transactions: TransactionsT, now: Callable[[], datetime]) -> None:
        self._transactions = transactions
        self._now = now


class _PlatformClockBinding[PlatformT]:
    def __init__(self, platform: PlatformT, now: Callable[[], datetime]) -> None:
        self._platform, self._now = platform, now


class _PlacementActivityBinding[TransactionsT]:
    def __init__(
        self,
        transactions: TransactionsT,
        active_count: Callable[[], int],
        now: Callable[[], datetime],
    ) -> None:
        self.transactions, self.active_count, self.now = transactions, active_count, now
