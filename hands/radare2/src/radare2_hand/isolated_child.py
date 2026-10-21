"""Unprivileged parser process: no bearer, signing material or Core context."""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from .runtime import Analyzer

TOOLS = frozenset({"radare2_import_start", "radare2_import_chunk", "radare2_import_finish", "radare2_import_abort",
    "radare2_list_binaries", "radare2_delete_binary", "radare2_binary_info", "radare2_functions",
    "radare2_disassemble", "radare2_strings", "radare2_xrefs"})


async def main():
    facts = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    if os.geteuid() != 1000 or os.getegid() != 1000 or int(facts["CapEff"].strip(), 16) != 0:
        raise ValueError("Unprivileged analysis execution identity required")
    os.chdir("/project-data")
    analyzer = Analyzer(Path("/project-data"))
    await analyzer.startup()
    print(json.dumps({"ready": True}), flush=True)
    try:
        while True:
            line = await asyncio.to_thread(sys.stdin.buffer.readline, 32769)
            if not line:
                return
            if len(line) > 32768:
                raise ValueError("Bounded supervisor input required")
            request = json.loads(line)
            if (not isinstance(request, dict) or set(request) != {"id", "tool", "arguments", "expires_at"}
                or UUID(request["id"]).version != 4 or request["tool"] not in TOOLS
                or not isinstance(request["arguments"], dict) or type(request["expires_at"]) is not int
                or not 0 < request["expires_at"] - time.time() <= 5):
                raise ValueError("Exact current analysis request required")
            try:
                async with asyncio.timeout(max(0, request["expires_at"] - time.time())):
                    value = await analyzer.execute(request["tool"], request["arguments"],
                                                   SimpleNamespace(expires_at=request["expires_at"]))
                result = {"content": [{"type": "text", "text": json.dumps(value, allow_nan=False)}],
                          "structuredContent": value, "isError": False}
            except (ValueError, TypeError, KeyError, OSError, TimeoutError):
                result = {"content": [{"type": "text", "text": "RADARE2_OPERATION_REJECTED_OR_UNAVAILABLE"}], "isError": True}
            reply = json.dumps({"id": request["id"], "result": result}, separators=(",", ":"), allow_nan=False)
            if len(reply.encode()) > 1_000_000:
                raise ValueError("Bounded analysis result required")
            print(reply, flush=True)
    finally:
        await analyzer.close()


if __name__ == "__main__":
    asyncio.run(main())
