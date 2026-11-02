"""A prepared session retains one immutable upstream tool catalogue."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionCatalogue:
    tool_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if not 0 < len(self.tool_names) <= 512:
            raise ValueError("Actual Serena runtime readiness required")


def require_original_catalogue(previous: str | None, announced: str) -> None:
    if previous is not None and previous != announced:
        raise ValueError("Immutable Serena tool catalogue changed")
