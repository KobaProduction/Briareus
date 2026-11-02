"""Native semantic acceptance against an isolated fixture, never a host project.

Native MCP/LSP evidence does not prove Core/Rauthy/Cedar admission.
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Protocol

from acceptance_lsp_languages import SemanticFixture, verify_files
from fastmcp.tools import Tool
from mcp.types import CallToolRequestParams, CallToolResult, TextContent
from pydantic import BaseModel, ValidationError


def text(result: CallToolResult) -> str:
    chunks = [item.text for item in result.content if isinstance(item, TextContent)]
    return "\n".join(chunks) + json.dumps(result.structured_content)


def session_from(result: CallToolResult) -> str:
    match = re.search(r"session id is [`]?([0-9a-f]+)", text(result))
    if match is None:
        raise AssertionError("Actual upstream session id required")
    return match.group(1)


def bind_session(
    call: CallToolRequestParams,
    catalogue: tuple[Tool, ...],
    session_id: str | None,
) -> CallToolRequestParams:
    metadata = next(item for item in catalogue if item.name == call.name)
    if "session_id" not in metadata.parameters.get("properties", {}):
        return call
    if session_id is None:
        raise AssertionError("Initial instructions must establish the upstream session")
    return CallToolRequestParams(
        name=call.name,
        arguments={**(call.arguments or {}), "session_id": session_id},
    )


class SemanticSession(Protocol):
    async def call(self, call: CallToolRequestParams) -> CallToolResult: ...


class ShellOutcome(BaseModel):
    return_code: int
    stdout: str
    stderr: str | None = None


def verify_shell_result(result: CallToolResult) -> None:
    for item in result.content:
        if not isinstance(item, TextContent):
            continue
        try:
            outcome = ShellOutcome.model_validate_json(item.text)
        except ValidationError:
            continue
        assert outcome.return_code == 0, outcome
        assert outcome.stdout.strip() == "updated", outcome
        return
    raise AssertionError("A concrete native shell outcome is required: " + text(result))


async def verify_semantics(
    session: SemanticSession,
    fixture: SemanticFixture,
    project: Path | None,
) -> None:
    await session.call(
        CallToolRequestParams(
            name="activate_project",
            arguments={"project": "Briareus project"},
        )
    )
    overview = await session.call(
        CallToolRequestParams(
            name="get_symbols_overview",
            arguments={"relative_path": fixture.library, "depth": 1},
        )
    )
    assert "Greeter" in text(overview)
    symbol = await session.call(
        CallToolRequestParams(
            name="find_symbol",
            arguments={
                "name_path_pattern": "Greeter/greet",
                "relative_path": fixture.library,
                "include_body": True,
            },
        )
    )
    assert fixture.original in text(symbol).replace(" ", "")
    references = await session.call(
        CallToolRequestParams(
            name="find_referencing_symbols",
            arguments={
                "name_path": "Greeter",
                "relative_path": fixture.library,
            },
        )
    )
    assert fixture.application in text(references)
    await session.call(
        CallToolRequestParams(
            name="replace_symbol_body",
            arguments={
                "name_path": "Greeter/greet",
                "relative_path": fixture.library,
                "body": fixture.body,
            },
        )
    )
    await session.call(
        CallToolRequestParams(
            name="rename_symbol",
            arguments={
                "name_path": "Greeter",
                "relative_path": fixture.library,
                "new_name": "Welcomer",
            },
        )
    )
    if project is not None:
        await verify_files(project, fixture)
    if fixture.command is not None:
        command = await session.call(
            CallToolRequestParams(
                name="execute_shell_command",
                arguments={"command": fixture.command, "cwd": "."},
            )
        )
        verify_shell_result(command)


async def main() -> None:
    from acceptance_deferred_lsp import main as deferred_main

    await deferred_main("python")


if __name__ == "__main__":
    asyncio.run(main())
