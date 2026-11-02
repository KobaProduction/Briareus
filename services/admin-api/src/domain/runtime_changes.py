"""Credential replacement is a single unambiguous runtime change."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BrowserTokenChange:
    token: str | None
    clear: bool

    def __post_init__(self) -> None:
        if self.token is not None and self.clear:
            raise ValueError("cannot set and clear external browser extension token together")

    @classmethod
    def requested(cls, token: str, *, supplied: bool, clear: bool) -> "BrowserTokenChange":
        return cls(token if supplied and token.strip() else None, clear)
