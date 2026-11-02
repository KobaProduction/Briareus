"""A passive Core command forwarded unchanged across private Node sockets."""

from pydantic import Field, model_validator

from .control import ControlCommand
from .models import Contract


class SignedBrowserObservation(Contract):
    command: ControlCommand
    signature: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def exact_action(self) -> "SignedBrowserObservation":
        if self.command.action != "observe_browser":
            raise ValueError("Passive browser observation command required")
        return self
