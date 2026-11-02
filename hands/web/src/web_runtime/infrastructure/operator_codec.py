"""Concrete operator commands at the authenticated WebSocket boundary."""

import json

from pydantic import BaseModel, StrictBool

from web_runtime.domain.operator import MouseInput, OperatorCommand


class OperatorWire(BaseModel):
    type: str | None = ""
    page_id: str | None = ""
    label: str | None = ""
    url: str | None = ""
    key: str | None = ""
    text: str | None = ""
    allowed: StrictBool | None = None
    event: str | None = ""
    x: float | None = 0
    y: float | None = 0
    button: str | None = "none"
    click_count: int | None = 0
    delta_x: float | None = 0
    delta_y: float | None = 0

    def command_value(self) -> str:
        if self.type == "set_label":
            return self.label or ""
        if self.type in {"navigate", "new_page"}:
            return self.url or ""
        if self.type == "key":
            return self.key or ""
        if self.type == "text":
            return self.text or ""
        return ""

    def to_command(self) -> OperatorCommand:
        mouse = None
        if self.type == "mouse":
            mouse = MouseInput(
                event_type=self.event or "",
                x=self.x or 0,
                y=self.y or 0,
                button=self.button or "none",
                click_count=self.click_count or 0,
                delta_x=self.delta_x or 0,
                delta_y=self.delta_y or 0,
            )
        return OperatorCommand(
            self.type or "", self.page_id or "", self.command_value(), self.allowed, mouse
        )


def decode_command(raw: str) -> OperatorCommand | None:
    value: object = json.loads(raw)
    if not isinstance(value, dict):
        return None
    return OperatorWire.model_validate(value).to_command()
