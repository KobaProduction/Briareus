"""Native upstream LSP workflow; run in the readonly UID1000 Serena image.

This verifies the actual MCP/LSP engine. Core/Rauthy/Cedar acceptance is a
separate orchestration step; this script never fabricates those credentials.
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import re
import sys
import time
from uuid import uuid4


def text(result):
    chunks = [item["text"] for item in result.get("content", []) if item.get("type") == "text"]
    return "\n".join(chunks) + json.dumps(result.get("structuredContent", {}))


async def main():
    workspace = Path("/project-data")
    relative = ".serena-acceptance-" + uuid4().hex
    project = workspace / relative
    project.mkdir(mode=0o700)
    (project / "library.py").write_text('class Greeter:\n    def greet(self) -> str:\n        return "hello"\n', encoding="utf-8")
    (project / "application.py").write_text('from library import Greeter\n\ndef render() -> str:\n    return Greeter().greet()\n', encoding="utf-8")
    env = dict(os.environ, BRIAREUS_SERENA_PROJECT_PATH=relative, SERENA_HOME="/home/hand/.serena")
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "serena_hand.isolated_child",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=env, cwd="/app/src", limit=1000001)
    try:
        raw = await asyncio.wait_for(process.stdout.readline(), timeout=180)
        if not raw:
            diagnostics = (await process.stderr.read()).decode(errors="replace")[-8000:]
            raise RuntimeError("Actual Serena startup failed: " + diagnostics)
        ready = json.loads(raw)
        assert ready["ready"] is True
        catalogue = {tool["name"]: tool for tool in ready["tools"]}
        session_id = None

        async def call(name, arguments):
            nonlocal session_id
            if "session_id" in catalogue[name]["parameters"].get("properties", {}):
                assert session_id
                arguments = dict(arguments, session_id=session_id)
            operation = str(uuid4())
            request = {"id": operation, "tool": name, "arguments": arguments, "expires_at": time.time() + 5}
            process.stdin.write(json.dumps(request).encode() + b"\n")
            await process.stdin.drain()
            result = json.loads(await asyncio.wait_for(process.stdout.readline(), timeout=7))
            assert result["id"] == operation
            assert result["result"].get("isError") is not True, (name, text(result["result"]))
            return result["result"]

        initial = await call("initial_instructions", {})
        match = re.search(r"session id is [`]?([0-9a-f]+)", text(initial))
        if match:
            session_id = match.group(1)
        await call("activate_project", {"project": "Briareus project"})
        overview = await call("get_symbols_overview", {"relative_path": "library.py", "depth": 1})
        assert "Greeter" in text(overview)
        symbol = await call("find_symbol", {"name_path_pattern": "Greeter/greet", "relative_path": "library.py", "include_body": True})
        assert "hello" in text(symbol)
        references = await call("find_referencing_symbols", {"name_path": "Greeter", "relative_path": "library.py"})
        assert "application.py" in text(references)
        await call("replace_symbol_body", {"name_path": "Greeter/greet", "relative_path": "library.py",
            "body": 'def greet(self) -> str:\n    return "updated"'})
        assert 'return "updated"' in (project / "library.py").read_text()
        await call("rename_symbol", {"name_path": "Greeter", "relative_path": "library.py", "new_name": "Welcomer"})
        assert "Welcomer" in (project / "library.py").read_text()
        assert "Welcomer" in (project / "application.py").read_text()
        command = await call("execute_shell_command", {"command": "python -c 'from application import render; print(render())'", "cwd": "."})
        assert "updated" in text(command)
        print(json.dumps({"upstream": "oraios/serena@2.0.0", "backend": "LSP",
            "workflow": "activate/overview/symbol/references/body-edit/cross-file-rename/execute",
            "fixture_relative_path": relative, "outcome": "passed"}))
    finally:
        if process.returncode is None:
            process.terminate()
        await process.wait()


if __name__ == "__main__":
    asyncio.run(main())
