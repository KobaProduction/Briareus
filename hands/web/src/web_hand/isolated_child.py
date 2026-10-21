"""Bounded private IPC for original Web/DevTools/Playwright MCP tool execution."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from contextlib import suppress
from pathlib import Path

from fastmcp import Client

from .node_runtime import STATIC_TOOLS, browser_metadata, create_runtime


def require_child_isolation():
    facts = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    if (os.geteuid() != 1000 or facts["NoNewPrivs"].strip() != "1"
        or int(facts["CapEff"].strip(), 16) != 0 or not os.statvfs("/").f_flag & os.ST_RDONLY
        or Path("/var/run/docker.sock").exists() or "BRIAREUS_DEPLOYMENT" in os.environ):
        raise ValueError("Unprivileged isolated browser child required")


async def main():
    require_child_isolation()
    mcp, browser, devtools, external = create_runtime()
    try:
        async with Client(mcp, timeout=None) as client:
            metadata = browser_metadata(await client.list_tools())
            allowed = {tool.name for tool in metadata}
            if not STATIC_TOOLS <= allowed or len(allowed) > 256:
                raise ValueError("Existing browser tool catalogue unavailable")
            encoded = json.dumps({"ready": True, "tools": [tool.model_dump(mode="json", by_alias=True)
                                 for tool in metadata]}, separators=(",", ":"), ensure_ascii=True)
            if len(encoded) > 750_000:
                raise ValueError("Browser metadata exceeds private IPC limit")
            sys.stdout.write(encoded + "\n")
            sys.stdout.flush()
            while True:
                line = await asyncio.to_thread(sys.stdin.buffer.readline, 65_537)
                if not line:
                    return
                if len(line) > 65_536 or not line.endswith(b"\n"):
                    raise ValueError("Browser supervisor command exceeds input limit")
                request = json.loads(line)
                if (not isinstance(request, dict) or set(request) != {"id", "tool", "arguments", "profile"}
                    or request["tool"] not in allowed or not isinstance(request["arguments"], dict)):
                    raise ValueError("Invalid browser supervisor command")
                profile = request["profile"]
                if not isinstance(profile, str) or re.fullmatch(r"/browser/session-[a-f0-9]{64}", profile) is None:
                    raise ValueError("Supervisor-selected session profile required")
                if browser.profile_dir != Path(profile) / "profile":
                    parent = Path(profile)
                    if parent.is_symlink():
                        raise ValueError("Private browser profile required")
                    parent.mkdir(mode=0o700, exist_ok=True)
                    browser.bind_unstarted_profile(parent / "profile", developer_access_enabled=
                        os.environ.get("BRIAREUS_NODE_WEB_DEVELOPER_ACCESS") == "1")
                try:
                    if request["tool"].startswith("external_") and request["tool"] not in {"external_status","external_connect","external_disconnect","external_reset"}:
                        result=await external.guarded_call(request["tool"][9:],request["arguments"])
                    else:
                        result = await client.call_tool(request["tool"], request["arguments"], raise_on_error=False)
                    reply = {"id": request["id"], "result": {
                        "content": [item.model_dump(mode="json", by_alias=True) for item in result.content],
                        "structuredContent": result.structured_content,
                        "isError": result.is_error,
                    }}
                except Exception:
                    reply = {"id": request["id"], "error": "WEB_OPERATION_FAILED"}
                encoded = json.dumps(reply, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
                if len(encoded) > 1_000_000:
                    encoded = json.dumps({"id": request["id"], "error": "WEB_OUTPUT_LIMIT"})
                sys.stdout.write(encoded + "\n")
                sys.stdout.flush()
    finally:
        with suppress(Exception):
            await external.disconnect()
        with suppress(Exception):
            await devtools._disconnect()
        devtools._stderr_forwarder.close()
        with suppress(Exception):
            await browser._stop_runtime(stop_display=True)


if __name__ == "__main__":
    asyncio.run(main())
