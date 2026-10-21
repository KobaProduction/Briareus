"""Original provider tools with fresh credentials and policies for every call."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
from uuid import UUID


async def run_provider_child(dispatch_type, accounts_type, failure_code):
    os.chdir("/project-data")
    facts = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    if (os.geteuid() != 1000 or int(facts["CapEff"].strip(), 16) != 0
            or facts["NoNewPrivs"].strip() != "1" or not os.statvfs("/").f_flag & os.ST_RDONLY
            or Path.cwd() != Path("/project-data")):
        raise ValueError("Unprivileged project-scoped child required")
    accounts = accounts_type([])
    dispatch = dispatch_type(accounts)
    print('{"ready":true}', flush=True)
    while True:
        raw = sys.stdin.buffer.readline(131073)
        if not raw:
            return
        if not raw.endswith(b"\n") or len(raw) > 131072:
            raise ValueError("Bounded private invocation required")
        request = json.loads(raw)
        if (not isinstance(request, dict) or set(request) not in ({"id", "tool", "arguments", "context", "expires_at"},{"id", "tool", "arguments", "context", "expires_at","background"})
                or type(request.get("background",False)) is not bool
                or UUID(request["id"]).version != 4
                or not isinstance(request["tool"], str) or not isinstance(request["arguments"], dict)
                or not isinstance(request["context"], dict)
                or set(request["context"]) - {"accounts", "policies"}
                or type(request["expires_at"]) not in (int, float)
                or not 0 < request["expires_at"] - time.time() <= 5):
            raise ValueError("Current exact provider invocation required")
        try:
            accounts.bind(request["context"].get("accounts", []))
            dispatch.configure(request["context"].get("policies", {}))
            result = await dispatch.call(request["tool"], request["arguments"])
            encoded = json.dumps(result, ensure_ascii=True, allow_nan=False)
            reply = {"content": [{"type": "text", "text": encoded}], "isError": False}
            if isinstance(result, dict):
                reply["structuredContent"] = result
        except Exception:
            reply = {"content": [{"type": "text", "text": failure_code}], "isError": True}
        finally:
            dispatch.clear()
            accounts.clear()
        if not request.get("background",False) and request["expires_at"] <= time.time():
            raise ValueError("Provider outcome expired")
        encoded = json.dumps({"id": request["id"], "result": reply}, ensure_ascii=True, allow_nan=False)
        if len(encoded.encode()) > 1000000:
            raise ValueError("Provider output exceeds budget")
        print(encoded, flush=True)
        # Rebuild only lightweight bound callables, never retain an account or
        # provider policy from a prior invocation. Imported libraries stay warm.
        accounts = accounts_type([])
        dispatch = dispatch_type(accounts)
