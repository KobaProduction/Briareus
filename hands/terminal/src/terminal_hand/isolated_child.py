"""Terminal tools inside the unprivileged, isolated execution process.

Only the supervisor owns authenticated IPC and signing keys. This child sees
plain tool arguments, its own project volume, and no Core/provider credentials.
The existing TerminalManager retains its kernel isolation preflight.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from common.settings import TerminalSettings
from modules.terminal._offline_executor import require_offline_executor
from modules.terminal.manager import TerminalManager
from modules.terminal.dispatch import TerminalToolDispatch
from hand_runtime.runtime_policy import runtime_policy


async def main() -> None:
    require_offline_executor()
    # Load/validate the shared typed policy during read-only preparation.
    # Its first import must not consume a short per-effect Core permit.
    runtime_policy()
    manager = TerminalManager(TerminalSettings(), admin_api=None)
    dispatch = TerminalToolDispatch(manager)
    allowed = set(dispatch.tools)
    if os.environ.get("TERMINAL_CHILD_READY") == "1":
        # The original read-only status callable checks private dispatch before
        # readiness. Workspaces and commands still require a Core permit.
        await dispatch.call("terminal_status", {})
        sys.stdout.write('{"ready":true}\n')
        sys.stdout.flush()
    while True:
        line = await asyncio.to_thread(sys.stdin.buffer.readline, 65_537)
        if not line:
            return
        if len(line) > 65_536 or not line.endswith(b"\n"):
            raise ValueError("Supervisor command exceeds worker budget")
        request = json.loads(line)
        if (not isinstance(request, dict) or set(request) != {"id", "tool", "arguments"}
            or request["tool"] not in allowed or not isinstance(request["arguments"], dict)):
            raise ValueError("Invalid supervisor command")
        try:
            result = await dispatch.call(request["tool"], request["arguments"])
            reply = {"id": request["id"], "result": {
                "content": [{"type": "text", "text": json.dumps(result, allow_nan=False)}],
                "structuredContent": result,
                "isError": False,
            }}
        except Exception:
            reply = {"id": request["id"], "error": "TERMINAL_OPERATION_FAILED"}
        encoded = json.dumps(reply, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        if len(encoded.encode("ascii")) > 1_000_000:
            encoded = json.dumps({"id": request["id"], "error": "TERMINAL_OUTPUT_LIMIT"})
        sys.stdout.write(encoded + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(main())
