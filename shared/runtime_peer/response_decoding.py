"""Typed owner response decoders; raw values stay inside the transport adapter."""

from collections.abc import Callable
from typing import Literal


def successful_reply[ReplyT](
    parse: Callable[[object], ReplyT], *, statuses: tuple[int, ...] = (200,)
) -> Callable[[int, object], ReplyT | None]:
    def decode(status: int, value: object) -> ReplyT | None:
        return parse(value) if status in statuses else None

    return decode


def confirmed_reply(status: int, value: object, flag: Literal["allowed", "recorded"]) -> bool:
    return (
        status == 200 and isinstance(value, dict) and set(value) == {flag} and value[flag] is True
    )
