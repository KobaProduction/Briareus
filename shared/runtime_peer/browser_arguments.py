"""Arguments of the existing human local-browser tools and deferred controls."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from pydantic_core import MISSING

from .tool_argument_decoding import decode_tool_arguments, selected_tool

BrowserToolName = Literal[
    "local_browser_status",
    "local_browser_pages",
    "local_browser_open",
    "local_browser_snapshot",
    "local_browser_back",
    "local_browser_forward",
    "local_browser_reload",
    "local_browser_close_page",
    "local_browser_set_viewport",
    "local_browser_click",
    "local_browser_fill",
    "local_browser_press",
    "local_browser_select_option",
    "local_browser_preview",
    "local_browser_reopen_closed_page",
    "local_browser_settings",
    "local_browser_input",
]


class BrowserArgumentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BrowserInspectionArguments(BrowserArgumentRecord):
    """Status, page inventory and closed-tab restoration accept no arguments."""


class BrowserPageArguments(BrowserArgumentRecord):
    page_id: str


class BrowserOpenArguments(BrowserArgumentRecord):
    url: str
    page_id: str | MISSING = MISSING


class BrowserSettingsArguments(BrowserArgumentRecord):
    section: str


class BrowserClickInput(BrowserArgumentRecord):
    kind: Literal["click"]
    x: float = Field(ge=0, le=7680, allow_inf_nan=False)
    y: float = Field(ge=0, le=4320, allow_inf_nan=False)
    button: Literal["left", "middle", "right"] = "left"
    click_count: int = Field(default=1, ge=1, le=2)


class BrowserWheelInput(BrowserArgumentRecord):
    kind: Literal["wheel"]
    x: float = Field(ge=0, le=7680, allow_inf_nan=False)
    y: float = Field(ge=0, le=4320, allow_inf_nan=False)
    delta_x: float = Field(ge=-10000, le=10000, allow_inf_nan=False)
    delta_y: float = Field(ge=-10000, le=10000, allow_inf_nan=False)


class BrowserKeyInput(BrowserArgumentRecord):
    kind: Literal["key"]
    key: str = Field(min_length=1, max_length=128)


class BrowserTextInput(BrowserArgumentRecord):
    kind: Literal["text"]
    text: str = Field(min_length=1, max_length=1024)


type BrowserInput = Annotated[
    BrowserClickInput | BrowserWheelInput | BrowserKeyInput | BrowserTextInput,
    Field(discriminator="kind"),
]


class BrowserInputArguments(BrowserPageArguments):
    events: list[BrowserInput] = Field(min_length=1, max_length=4)


class BrowserSnapshotArguments(BrowserPageArguments):
    max_text_chars: int | MISSING | None = MISSING
    max_elements: int | MISSING | None = MISSING


class BrowserViewportArguments(BrowserPageArguments):
    width: int
    height: int


class BrowserElementArguments(BrowserPageArguments):
    ref: str


class BrowserFillArguments(BrowserElementArguments):
    value: str
    press_enter: bool | MISSING = MISSING


class BrowserPressArguments(BrowserElementArguments):
    key: str


class BrowserSelectArguments(BrowserElementArguments):
    value: str


type BrowserArguments = (
    BrowserInputArguments
    | BrowserSnapshotArguments
    | BrowserViewportArguments
    | BrowserFillArguments
    | BrowserPressArguments
    | BrowserSelectArguments
    | BrowserElementArguments
    | BrowserPageArguments
    | BrowserOpenArguments
    | BrowserSettingsArguments
    | BrowserInspectionArguments
)

BROWSER_ARGUMENTS: dict[str, type[BrowserArguments]] = {
    "local_browser_status": BrowserInspectionArguments,
    "local_browser_pages": BrowserInspectionArguments,
    "local_browser_reopen_closed_page": BrowserInspectionArguments,
    "local_browser_settings": BrowserSettingsArguments,
    "local_browser_input": BrowserInputArguments,
    "local_browser_open": BrowserOpenArguments,
    "local_browser_snapshot": BrowserSnapshotArguments,
    "local_browser_back": BrowserPageArguments,
    "local_browser_forward": BrowserPageArguments,
    "local_browser_reload": BrowserPageArguments,
    "local_browser_close_page": BrowserPageArguments,
    "local_browser_set_viewport": BrowserViewportArguments,
    "local_browser_click": BrowserElementArguments,
    "local_browser_fill": BrowserFillArguments,
    "local_browser_press": BrowserPressArguments,
    "local_browser_select_option": BrowserSelectArguments,
    "local_browser_preview": BrowserPageArguments,
}


class WebOperationStartArguments(BrowserArgumentRecord):
    tool: BrowserToolName
    arguments: BrowserArguments

    @field_validator("arguments", mode="before")
    @classmethod
    def tool_arguments(cls, value: object, info: ValidationInfo[object]) -> BrowserArguments:
        return decode_tool_arguments(selected_tool(info), value, BROWSER_ARGUMENTS)


class WebOperationControlArguments(BrowserArgumentRecord):
    operation_id: str


class WebOperationPollArguments(WebOperationControlArguments):
    tool: BrowserToolName


type WebArguments = (
    WebOperationStartArguments
    | WebOperationPollArguments
    | WebOperationControlArguments
    | BrowserArguments
)

WEB_ARGUMENTS: dict[str, type[WebArguments]] = {
    **BROWSER_ARGUMENTS,
    "web_operation_start": WebOperationStartArguments,
    "web_operation_poll": WebOperationPollArguments,
    "web_operation_cancel": WebOperationControlArguments,
}
