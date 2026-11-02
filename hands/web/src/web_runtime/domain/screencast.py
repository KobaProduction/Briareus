"""Browser frame data retained in the bounded operator queue."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FrameMetadata:
    offset_top: float
    page_scale_factor: float
    device_width: float
    device_height: float
    scroll_offset_x: float
    scroll_offset_y: float
    timestamp: float | None = None
    monotonic_timestamp: float | None = None


@dataclass(frozen=True, slots=True)
class ScreenFrame:
    data: str
    metadata: FrameMetadata
