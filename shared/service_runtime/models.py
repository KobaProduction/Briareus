from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, validate_call


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
    )


_STRICT_CALL_CONFIG = ConfigDict(strict=True, arbitrary_types_allowed=True)


def validated_call[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    return validate_call(
        config=_STRICT_CALL_CONFIG,
        validate_return=True,
    )(function)
