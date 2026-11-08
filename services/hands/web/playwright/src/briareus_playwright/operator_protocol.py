"""Validated browser operator commands and Chromium screencast event payloads."""

from __future__ import annotations

from typing import Annotated, Literal

from briareus_json_values import JsonObject, json_loads
from pydantic import BaseModel, ConfigDict, Field, StrictBool, TypeAdapter, ValidationError


class OperatorMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")


class StateCommand(OperatorMessage):
    type: Literal[
        "refresh_state",
        "back",
        "reload",
        "clean_app",
        "close_all_pages",
        "clean_browser",
        "reopen_closed_page",
        "release",
    ]


class PageCommand(OperatorMessage):
    type: Literal["select_page", "navigate", "new_page", "close_page"]
    page_id: str = ""
    url: str = ""


class LabelCommand(OperatorMessage):
    type: Literal["set_label"]
    page_id: str = ""
    label: str = ""


class AccessCommand(OperatorMessage):
    type: Literal["set_page_agent_access", "set_agent_access", "set_developer_access"]
    page_id: str = ""
    allowed: StrictBool


class MouseCommand(OperatorMessage):
    type: Literal["mouse"]
    page_id: str = ""
    event: str = ""
    x: float = 0
    y: float = 0
    button: str = "none"
    click_count: int = 0
    delta_x: float = 0
    delta_y: float = 0


class KeyCommand(OperatorMessage):
    type: Literal["key"]
    page_id: str = ""
    key: str = ""


class TextCommand(OperatorMessage):
    type: Literal["text"]
    page_id: str = ""
    text: str = ""


class ClipboardCommand(OperatorMessage):
    type: Literal["clipboard_read"]
    page_id: str = ""
    request_id: str = Field(min_length=1, max_length=128)


type OperatorCommand = Annotated[
    StateCommand
    | PageCommand
    | LabelCommand
    | AccessCommand
    | MouseCommand
    | KeyCommand
    | TextCommand
    | ClipboardCommand,
    Field(discriminator="type"),
]
_COMMANDS: TypeAdapter[OperatorCommand] = TypeAdapter(OperatorCommand)


def parse_command(raw: str) -> OperatorCommand | None:
    try:
        payload = json_loads(raw)
    except ValueError as exc:
        raise ValueError("invalid JSON") from exc
    if not isinstance(payload, dict):
        return None
    try:
        return _COMMANDS.validate_python(payload)
    except ValidationError as exc:
        # Unknown commands remain forward compatible, as in the original protocol.
        if all(
            error["type"] in {"union_tag_invalid", "union_tag_not_found"} for error in exc.errors()
        ):
            return None
        raise ValueError("invalid browser operator command") from exc


class ScreencastFrame(OperatorMessage):
    sessionId: int | None = None
    data: str = ""
    metadata: JsonObject = Field(default_factory=dict)
