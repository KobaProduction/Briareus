"""A passive, bounded last frame belongs to one verified execution context."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AgentBrowserOwner:
    project_uuid: UUID
    placement_uuid: UUID
    actor_uuid: UUID
    agent_session_uuid: UUID
    grant_revision: int


@dataclass(frozen=True, slots=True)
class AgentBrowserFrame:
    owner: AgentBrowserOwner
    request_uuid: UUID
    captured_at: float
    page_id: str
    url: str
    title: str
    png: bytes

    def __post_init__(self) -> None:
        if (
            not self.png.startswith(b"\x89PNG\r\n\x1a\n")
            or len(self.png) > 650_000
            or not 0 < len(self.page_id) <= 256
            or len(self.url) > 16_384
            or len(self.title) > 4096
        ):
            raise ValueError("Bounded browser viewport observation required")


class AgentBrowserObservations:
    def __init__(self) -> None:
        self.generation = 0
        self._frame: AgentBrowserFrame | None = None

    def clear(self) -> None:
        self.generation += 1
        self._frame = None

    def capture(self, generation: int, frame: AgentBrowserFrame) -> None:
        if generation == self.generation:
            self._frame = frame

    def read(self, owner: AgentBrowserOwner) -> AgentBrowserFrame | None:
        """Selection is not authorization; the caller must verify human visibility."""
        frame = self._frame
        return frame if frame is not None and frame.owner == owner else None
