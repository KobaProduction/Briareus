"""Native isolated-parent LSP acceptance with renewed short execution leases.

Fixture identities are not Rauthy/Cedar acceptance. No host workspace is mounted.
"""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from uuid import uuid4

from acceptance_lsp import bind_session, session_from, text, verify_semantics
from acceptance_lsp_languages import Language, descriptor, parse_language
from mcp.types import CallToolRequestParams, CallToolResult
from serena_hand.supervisor import SerenaSupervisor

from hand_runtime.deferred_calls import OperationView
from node_protocol.effect import NodeEffectPermit


async def fixture_helper(language: Language, relative: str, *, verify: bool) -> None:
    option = "--verify-relative" if verify else "--prepare-relative"
    process = await asyncio.create_subprocess_exec(
        "/app/.venv/bin/python",
        "-m",
        "acceptance_lsp_languages",
        language,
        option,
        relative,
        user=1000,
        group=1000,
        extra_groups=[],
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": "/app/src:/acceptance"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(15):
            _, stderr = await process.communicate()
        if process.returncode:
            raise RuntimeError("Owned fixture helper failed: " + stderr.decode()[-1000:])
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def cohort_states() -> tuple[str, ...]:
    states: list[str] = []
    for path in Path("/proc").glob("[0-9]*/status"):
        try:
            facts = path.read_text().splitlines()
        except (FileNotFoundError, ProcessLookupError):
            continue
        uid = next(line for line in facts if line.startswith("Uid:")).split()[1]
        state = next(line for line in facts if line.startswith("State:")).split()[1]
        if uid == "1000" and state not in {"Z", "X"}:
            states.append(state)
    return tuple(states)


class DeferredSession:
    def __init__(self, supervisor: SerenaSupervisor) -> None:
        self.supervisor = supervisor
        self.actor, self.session = uuid4(), uuid4()
        self.node, self.placement, self.project, self.workspace = (uuid4() for _ in range(4))
        self.upstream_session: str | None = None
        self.paused = False

    def permit(self, tool: str) -> NodeEffectPermit:
        now = int(time.time())
        return NodeEffectPermit(
            module="serena",
            node_uuid=self.node,
            placement_uuid=self.placement,
            project_uuid=self.project,
            workspace_uuid=self.workspace,
            actor_uuid=self.actor,
            agent_session_uuid=self.session,
            request_uuid=uuid4(),
            grant_revision=1,
            fingerprint="a" * 64,
            body_digest="b" * 64,
            bearer_digest="c" * 64,
            arguments_digest="d" * 64,
            method="tools/call",
            tool=tool,
            resource_id="workspace:" + "a" * 80,
            issued_at=now,
            expires_at=now + 4,
        )

    @staticmethod
    def view(result: CallToolResult) -> OperationView:
        assert not result.is_error, text(result)
        return OperationView.model_validate_json(json.dumps(result.structured_content))

    async def verify_pause(self) -> None:
        await asyncio.sleep(6)
        assert self.supervisor.lease.paused
        states = await asyncio.to_thread(cohort_states)
        assert states and all(state.upper() == "T" for state in states), states
        self.paused = True

    async def foreground(self, call: CallToolRequestParams) -> CallToolResult:
        catalogue = self.supervisor.catalogue
        assert catalogue is not None
        command = bind_session(call, catalogue, self.upstream_session)
        result = await self.supervisor.call(command, self.permit(command.name))
        assert not result.is_error, (command.name, text(result))
        return result

    async def call(self, call: CallToolRequestParams) -> CallToolResult:
        catalogue = self.supervisor.catalogue
        assert catalogue is not None
        command = bind_session(call, catalogue, self.upstream_session)
        started = await self.supervisor.call(
            CallToolRequestParams(
                name="serena_operation_start",
                arguments={
                    "tool": command.name,
                    "arguments": command.arguments or {},
                },
            ),
            self.permit("serena_operation_start"),
        )
        state = self.view(started)
        if command.name == "get_symbols_overview" and not self.paused:
            await self.verify_pause()
        async with asyncio.timeout(90):
            while state.state == "running":
                result = await self.supervisor.call(
                    CallToolRequestParams(
                        name="serena_operation_poll",
                        arguments={
                            "operation_id": state.operation_id,
                            "tool": command.name,
                        },
                    ),
                    self.permit("serena_operation_poll"),
                )
                state = self.view(result)
                if state.state == "running":
                    await asyncio.sleep(1)
        assert state.state == "completed", state
        assert state.result is not None and not state.result.is_error, state
        return state.result


async def verify_foreground(session: DeferredSession, language: Language) -> None:
    selected = descriptor(language)
    symbol = await session.foreground(
        CallToolRequestParams(
            name="find_symbol",
            arguments={
                "name_path_pattern": "Welcomer/greet",
                "relative_path": selected.library,
                "include_body": True,
            },
        )
    )
    expected = "updated" if language == "python" else "709"
    assert expected in text(symbol), text(symbol)


async def main(language: Language) -> None:
    assert os.geteuid() == 0
    mapping = await asyncio.to_thread(Path("/proc/self/uid_map").read_text)
    assert int(mapping.split()[1]) != 0
    relative = ".deferred-" + language + "-" + uuid4().hex
    await fixture_helper(language, relative, verify=False)
    supervisor = SerenaSupervisor(relative)
    session = DeferredSession(supervisor)
    semantics_complete = False
    try:
        await supervisor.warmup()
        session.upstream_session = session_from(
            await session.call(
                CallToolRequestParams(
                    name="initial_instructions",
                    arguments={},
                )
            )
        )
        await verify_semantics(session, descriptor(language), None)
        semantics_complete = True
        assert session.paused
        await verify_foreground(session, language)
    finally:
        await supervisor.close()
        if semantics_complete:
            await fixture_helper(language, relative, verify=True)
            print("Owned fixture files verified after semantic edits", flush=True)
    print(
        json.dumps(
            {
                "native_deferred_lsp": language,
                "semantic_workflow": "passed",
                "foreground_after_preparation": "passed",
                "uid_cohort_paused_after_expiry": session.paused,
                "owned_fixture_deleted": True,
            }
        ),
        flush=True,
    )


class Options(argparse.Namespace):
    language: str


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language", choices=["python", "typescript", "cpp"])
    options = Options()
    parser.parse_args(namespace=options)
    asyncio.run(main(parse_language(options.language)))


if __name__ == "__main__":
    cli()
