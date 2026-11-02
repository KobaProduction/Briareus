"""Project private-read requests; signed arguments stay separate from defaulted queries."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from files_hand.domain.private_read import (
    PrivateFileQuery,
    PrivatePathAction,
    PrivatePathQuery,
    PrivateReadQuery,
    PrivateReadWindow,
)
from hand_runtime.private_call import PrivateToolCall


class _PathArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    path: str = ""


class _ReadArguments(_PathArguments):
    offset: StrictInt = 0
    length: StrictInt = 262_144


class FilesCall(PrivateToolCall):
    permit: str = Field(min_length=80, max_length=8192)

    @model_validator(mode="after")
    def require_call_budget(self) -> Self:
        self.require_budget(4)
        return self

    def query(self) -> PrivateFileQuery:
        if self.call.name == "file_read":
            read = _ReadArguments.model_validate(self.call.arguments or {})
            return PrivateReadQuery(read.path, PrivateReadWindow(read.offset, read.length))
        action = PrivatePathAction(self.call.name)
        path = _PathArguments.model_validate(self.call.arguments or {})
        return PrivatePathQuery(path.path, action)
