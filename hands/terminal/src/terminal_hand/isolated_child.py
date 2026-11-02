"""Terminal tools inside the unprivileged, isolated execution process.

Only the supervisor owns authenticated IPC and signing keys. This child sees
plain tool arguments, its own project volume, and no Core/provider credentials.
The existing TerminalManager retains its kernel isolation preflight.
"""

from __future__ import annotations

import asyncio
import os
import sys

from mcp.types import CallToolRequestParams
from modules.terminal._offline_executor import require_offline_executor
from modules.terminal.dispatch import TerminalToolDispatch

from common.settings import TerminalSettings
from hand_runtime.provider_ipc import PreparationReady
from hand_runtime.runtime_policy import runtime_policy
from modules.terminal.manager import TerminalManager
from terminal_hand.application.execute_worker import ExecuteWorkerCommand
from terminal_hand.infrastructure.worker_codec import (
    BoundWorkerDispatch,
    decode_command,
    encode_outcome,
)
from terminal_hand.infrastructure.worker_messages import MAX_PRIVATE_WORKER_BYTES


async def main() -> None:
    require_offline_executor()
    # Load/validate the shared typed policy during read-only preparation.
    # Its first import must not consume a short per-effect Core permit.
    runtime_policy()
    manager = TerminalManager(TerminalSettings(), admin_api=None)
    dispatch = TerminalToolDispatch(manager)
    tools = frozenset(dispatch.tools)
    if os.environ.get("TERMINAL_CHILD_READY") == "1":
        # The original read-only status callable checks private dispatch before
        # readiness. Workspaces and commands still require a Core permit.
        await dispatch.call(CallToolRequestParams(name="terminal_status", arguments={}))
        sys.stdout.write(PreparationReady(ready=True).model_dump_json() + "\n")
        sys.stdout.flush()
    while True:
        line = await asyncio.to_thread(sys.stdin.buffer.readline, MAX_PRIVATE_WORKER_BYTES + 1)
        if not line:
            return
        request = decode_command(line)
        execute = ExecuteWorkerCommand(BoundWorkerDispatch(dispatch.call, request.call), tools)
        scope = request.human
        if scope is not None:
            if scope.creation_id is not None and scope.creation_id != request.id.hex:
                raise ValueError("Human job creation identity changed")
            manager.begin_human_command(scope.namespace, scope.creation_id, scope.allowed_jobs)
        try:
            encoded = encode_outcome(request.id, await execute.execute(request.call.name))
        finally:
            manager.end_human_command()
        sys.stdout.write(encoded + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(main())
