"""Precisely typed scalar Lua execution on the asynchronous decoded Valkey client."""

from collections.abc import Awaitable
from typing import cast

from valkey.asyncio import Valkey


async def eval_script(
    client: Valkey, script: str, key_count: int, *values: str | int
) -> str | int | None:
    # The SDK shares sync/async command stubs. This adapter owns the actual async client.
    result = client.eval(script, key_count, *(str(value) for value in values))
    return await cast(Awaitable[str | int | None], result)
