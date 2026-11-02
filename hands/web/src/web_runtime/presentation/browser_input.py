"""Validate UI input into the existing operator command vocabulary."""

from runtime_peer.browser_arguments import (
    BrowserClickInput,
    BrowserInput,
    BrowserKeyInput,
    BrowserTextInput,
)
from web_runtime.domain.operator import MouseInput, OperatorCommand


def input_command(page_id: str, event: BrowserInput) -> OperatorCommand:
    if isinstance(event, BrowserKeyInput):
        return OperatorCommand("key", page_id, event.key)
    if isinstance(event, BrowserTextInput):
        return OperatorCommand("text", page_id, event.text)
    if isinstance(event, BrowserClickInput):
        return OperatorCommand(
            "click",
            page_id,
            mouse=MouseInput(
                "mousePressed",
                event.x,
                event.y,
                event.button,
                event.click_count,
                0,
                0,
            ),
        )
    return OperatorCommand(
        "mouse",
        page_id,
        mouse=MouseInput(
            "mouseWheel",
            event.x,
            event.y,
            "none",
            0,
            event.delta_x,
            event.delta_y,
        ),
    )
