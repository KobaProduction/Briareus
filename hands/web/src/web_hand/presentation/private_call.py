"""The existing private browser-open request and its explicit URL argument."""

from typing import Self

from pydantic import Field, model_validator

from hand_runtime.private_call import PrivateToolCall
from runtime_peer.runtime_arguments import PrivateBrowserOpenArguments


class BrowserCall(PrivateToolCall):
    permit: str = Field(min_length=80, max_length=8192)

    @model_validator(mode="after")
    def require_call_budget(self) -> Self:
        self.require_budget(1)
        return self

    def open_url(self) -> str:
        return PrivateBrowserOpenArguments.model_validate(self.call.arguments or {}).url
