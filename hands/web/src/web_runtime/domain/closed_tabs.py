"""Bounded recent-tab history preserves the native operator's observation order."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


@dataclass(frozen=True)
class ClosedTab:
    url: str
    label: str
    page_agent_access: bool


@dataclass(frozen=True)
class ClosedTabs:
    entries: tuple[ClosedTab, ...] = ()

    def __post_init__(self) -> None:
        if len(self.entries) > 20:
            raise ValueError("Closed browser history exceeds its capacity")

    def __bool__(self) -> bool:
        return bool(self.entries)

    def remember(self, tab: ClosedTab) -> ClosedTabs:
        return ClosedTabs((*self.entries, tab)[-20:])

    def take_latest(self) -> RestoredTab:
        if not self.entries:
            raise ValueError("no recently closed browser tab")
        return RestoredTab(self.entries[-1], ClosedTabs(self.entries[:-1]))


class RestoredTab(NamedTuple):
    tab: ClosedTab
    history: ClosedTabs
