"""CDP screencast ingress and the existing browser operator event shapes.

Metadata follows ChromeDevTools/devtools-protocol Page.ScreencastFrameMetadata.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from web_runtime.browser_models import OperatorState
from web_runtime.domain.screencast import FrameMetadata, ScreenFrame


class ScreencastMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)
    offset_top: float = Field(alias="offsetTop")
    page_scale_factor: float = Field(alias="pageScaleFactor")
    device_width: float = Field(alias="deviceWidth")
    device_height: float = Field(alias="deviceHeight")
    scroll_offset_x: float = Field(alias="scrollOffsetX")
    scroll_offset_y: float = Field(alias="scrollOffsetY")
    timestamp: float | None = None
    monotonic_timestamp: float | None = Field(default=None, alias="monotonicTimestamp")

    def to_metadata(self) -> FrameMetadata:
        return FrameMetadata(
            self.offset_top,
            self.page_scale_factor,
            self.device_width,
            self.device_height,
            self.scroll_offset_x,
            self.scroll_offset_y,
            self.timestamp,
            self.monotonic_timestamp,
        )


class ScreencastSession(BaseModel):
    session_id: int = Field(alias="sessionId")


class ScreencastFrame(ScreencastSession):
    data: str
    metadata: ScreencastMetadata

    def to_frame(self) -> ScreenFrame:
        return ScreenFrame(self.data, self.metadata.to_metadata())


class OperatorFrameEvent(BaseModel):
    type: Literal["frame"] = "frame"
    page_id: str
    data: str
    metadata: ScreencastMetadata
    url: str


class OperatorStateEvent(OperatorState):
    type: Literal["state"] = "state"


class OperatorErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
