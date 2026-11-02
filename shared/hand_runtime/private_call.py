"""Typed private headers composed with the standard SDK tool request."""

import json
from typing import Self

from mcp.types import CallToolRequestParams
from pydantic import BaseModel, ConfigDict, ModelWrapValidatorHandler, model_validator


class PrivateToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    call: CallToolRequestParams

    def require_budget(self, maximum_arguments: int) -> None:
        if (
            not 1 <= len(self.call.name) <= 128
            or len(self.call.arguments or {}) > maximum_arguments
        ):
            raise ValueError("Bounded private tool call required")

    @model_validator(mode="wrap")
    @classmethod
    def from_private_wire(cls, value: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        if isinstance(value, cls):
            return handler(value)
        if not isinstance(value, dict):
            raise ValueError("Exact private tool command required")
        if "call" in value:
            # Only internal constructors can supply a real SDK request. A
            # nested JSON call never expands the existing flat wire protocol.
            if not isinstance(value["call"], CallToolRequestParams):
                raise ValueError("Exact private tool command required")
            return handler(value)
        name, arguments = value.get("tool"), value.get("arguments")
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise ValueError("Exact private tool arguments required")
        headers = {key: item for key, item in value.items() if key not in {"tool", "arguments"}}
        return handler({**headers, "call": CallToolRequestParams(name=name, arguments=arguments)})

    def wire_json(
        self,
        *,
        exclude_none: bool = False,
        exclude_unset: bool = False,
        sort_keys: bool = False,
        compact: bool = False,
    ) -> str:
        headers = self.model_dump(
            mode="json",
            exclude={"call"},
            exclude_none=exclude_none,
            exclude_unset=exclude_unset,
        )
        return json.dumps(
            {**headers, "tool": self.call.name, "arguments": self.call.arguments or {}},
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=sort_keys,
            separators=(",", ":") if compact else None,
        )
