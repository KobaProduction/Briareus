"""Bounded read-only browser selector and observed-frame wire records."""

from pydantic import UUID4, Field

from .domain.browser_observation import (
    BrowserObservationTarget,
    BrowserObservedFrame,
    NodeBrowserObservation,
)
from .models import Contract

OBSERVATION_PATH = "/internal/v1/node/browser-observation"


class BrowserObservationSelector(Contract):
    project_uuid: UUID4
    placement_uuid: UUID4
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    actor_uuid: UUID4
    agent_session_uuid: UUID4
    grant_revision: int = Field(strict=True, ge=1, lt=2**63)

    def observation(self) -> BrowserObservationTarget:
        return BrowserObservationTarget(
            self.project_uuid,
            self.placement_uuid,
            self.fingerprint,
            self.actor_uuid,
            self.agent_session_uuid,
            self.grant_revision,
        )


class BrowserObservedFrameWire(Contract):
    source_request_uuid: UUID4
    captured_at: float = Field(strict=True, gt=0, allow_inf_nan=False)
    page_id: str = Field(min_length=1, max_length=256)
    url: str = Field(max_length=16_384)
    title: str = Field(max_length=4096)
    png_base64: str = Field(max_length=866_668, pattern=r"^[A-Za-z0-9+/]*={0,2}$")

    def observation(self) -> BrowserObservedFrame:
        return BrowserObservedFrame(
            self.source_request_uuid,
            self.captured_at,
            self.page_id,
            self.url,
            self.title,
            self.png_base64,
        )


class BrowserObservationWire(Contract):
    target: BrowserObservationSelector
    frame: BrowserObservedFrameWire | None

    def observation(self) -> NodeBrowserObservation:
        return NodeBrowserObservation(
            self.target.observation(),
            self.frame.observation() if self.frame else None,
        )
