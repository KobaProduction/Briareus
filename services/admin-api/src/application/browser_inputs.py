"""Bounded browser management command bodies, reused by HTTP and MCP adapters."""

from pydantic import BaseModel, ConfigDict, Field


class BrowserPageSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_id: str = Field(min_length=1, max_length=255)


class ViewportPayload(BrowserPageSelection):
    width: int = Field(ge=320, le=7680)
    height: int = Field(ge=240, le=4320)


class BrowserThemePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    color_scheme: str = Field(pattern="^(system|light|dark)$")
