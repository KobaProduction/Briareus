"""Opt-in native packaged-image audit; no Core/Cedar acceptance is implied.

Run only in a disposable rootless container with the production supervisor's
UID/capability/mount isolation and a public-only Web egress proxy. This audit
uses private worker IPC directly so a cold Chromium diagnostic can finish;
the production five-second effect lease is independently enforced upstream.
"""
from __future__ import annotations

import asyncio
import json
import uuid

from web_hand.node_runtime import STATIC_TOOLS
from web_hand.node_supervisor import WebSupervisor, require_supervisor_isolation


async def main():
    require_supervisor_isolation()
    supervisor = WebSupervisor()
    try:
        await supervisor.start("a" * 64)
        names = {tool["name"] for tool in supervisor.metadata}
        assert len(STATIC_TOOLS) == 25 and STATIC_TOOLS <= names
        assert all("curl" not in name.lower() for name in names)
        assert all(name.startswith(("local_", "external_")) for name in names)
        print(json.dumps({"stage": "metadata", "count": len(names), "static": 25}), flush=True)

        async def call(tool, arguments=None):
            request = {"id": uuid.uuid4().hex, "tool": tool,
                       "arguments": arguments or {}, "profile": str(supervisor.profile)}
            supervisor.child.stdin.write((json.dumps(request) + "\n").encode())
            await supervisor.child.stdin.drain()
            raw = await asyncio.wait_for(supervisor.child.stdout.readline(), 120)
            reply = json.loads(raw)
            assert reply.get("id") == request["id"], reply
            result = reply.get("result", {})
            print(json.dumps({"stage": tool, "reply": reply}, ensure_ascii=True)[:16000], flush=True)
            assert not reply.get("error") and not result.get("isError"), reply
            value = result.get("structuredContent")
            if value is None:
                value = json.loads(result["content"][0]["text"])
            return value

        external = await call("external_status")
        assert external.get("enabled", external.get("external_enabled")) is False, external
        await call("local_browser_diagnostics")
        status = await call("local_browser_status")
        assert status["running"] and status["cdp_reachable"], status
        opened = await call("local_browser_open", {"url": "https://example.com"})
        page_id = opened["page_id"]
        snapshot = await call("local_browser_snapshot", {"page_id": page_id})
        assert "Example Domain" in json.dumps(snapshot), snapshot
        await call("local_browser_debug_target", {"page_id": page_id})
        links = [item for item in snapshot.get("elements", []) if item.get("href")]
        if links:
            await call("local_browser_click", {"page_id": page_id, "ref": links[0]["ref"]})
        print(json.dumps({"outcome": "passed", "scope": "native-browser-only"}), flush=True)
    finally:
        await supervisor.stop()


if __name__ == "__main__":
    asyncio.run(main())
