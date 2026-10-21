"""Packaged unified Analysis SDK/ELF workflow in a disposable rootless placement.

Run against the BUILT image with only this test directory mounted read-only;
do not override its packaged runtime/source. Fixture signatures exercise the
Node/SDK boundary and are deliberately not Rauthy/Cedar or external acceptance.
No uploaded binary is executed: the real pinned radare2 parses a copied ELF.
"""
from __future__ import annotations

import base64
import asyncio
import hashlib
import json
import os
import struct
import time
import unittest
from pathlib import Path
from uuid import uuid4

import httpx2 as httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from node_protocol import Deployment, ModuleRelease, ResourceLimits, WorkspaceMount
from node_protocol.control import canonical
from node_protocol.effect import NodeEffectPermit, sign_permit
from node_protocol.module_effects import parse_request, resource_id
from reverse_hand.node_server import create_app

TOOLS = frozenset({"radare2_import_start", "radare2_import_chunk", "radare2_import_finish", "radare2_import_abort",
    "radare2_list_binaries", "radare2_delete_binary", "radare2_binary_info", "radare2_functions",
    "radare2_disassemble", "radare2_strings", "radare2_xrefs"})


class UnifiedAnalysisTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_facade_native_elf_and_private_storage_boundary(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(os.statvfs("/").f_flag & os.ST_RDONLY)
        self.assertEqual({path.name for path in Path("/sys/class/net").iterdir()}, {"lo"})
        self.assertEqual((Path("/project-data").stat().st_uid,
                          Path("/project-data").stat().st_mode & 0o777), (1000, 0o700))
        elf = Path("/usr/bin/true").read_bytes()
        self.assertTrue(elf.startswith(b"\x7fELF"))
        digest = hashlib.sha256(elf).hexdigest()
        key = Ed25519PrivateKey.generate()
        project, node, storage, placement, actor, session = (uuid4() for _ in range(6))
        spec = Deployment(id=placement, node_uuid=node, project_uuid=project,
            release=ModuleRelease(module="reverse", image="registry.example/analysis@sha256:" + "a"*64,
                                  lifecycle="sessionful"),
            limits=ResourceLimits(memory_bytes=1536*1024**2, cpu_millis=750, pids=128),
            workspace=WorkspaceMount(id=storage), effect_verify_key=key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode())
        app = create_app(spec)
        bearer = "Bearer native-radare2-fixture-not-provider-identity"
        async with app.app.router.lifespan_context(app.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),
                base_url="http://"+spec.container_name+".reverse") as client:
                sequence = 0

                async def frame(method, tool=None, arguments=None, **changes):
                    nonlocal sequence
                    sequence += 1
                    wire = {"jsonrpc":"2.0", "id":sequence, "method":method}
                    if tool is not None:
                        wire["params"] = {"name":tool, "arguments":arguments or {}}
                    body = json.dumps(wire, separators=(",", ":")).encode()
                    self.assertLessEqual(len(body), 32768)
                    parsed, now = parse_request("reverse", body), int(time.time())
                    values = dict(module="reverse", node_uuid=node, placement_uuid=placement,
                        project_uuid=project, workspace_uuid=storage, actor_uuid=actor,
                        agent_session_uuid=session, request_uuid=uuid4(), grant_revision=1,
                        fingerprint=spec.fingerprint, body_digest=hashlib.sha256(body).hexdigest(),
                        bearer_digest=hashlib.sha256(bearer.encode()).hexdigest(),
                        arguments_digest=hashlib.sha256(canonical(parsed.arguments)).hexdigest(),
                        method=parsed.method, tool=parsed.tool, resource_id=resource_id("reverse", node, project, storage),
                        issued_at=now, expires_at=now+5)
                    values.update(changes)
                    return await client.post("/mcp", content=body, headers={"content-type":"application/json",
                        "authorization":bearer, "accept":"application/json, text/event-stream",
                        "mcp-protocol-version":"2025-11-25",
                        "x-briareus-node-permit":sign_permit(NodeEffectPermit(**values), key)})

                async def tool(name, arguments=None, *, error=False):
                    response = await frame("tools/call", "analysis_call", {"engine":"radare2", "tool":name, "arguments":arguments or {}})
                    self.assertEqual(response.status_code, 200, response.text)
                    result = response.json()["result"]
                    self.assertEqual(bool(result.get("isError")), error, result)
                    return result.get("structuredContent")

                listed = await frame("tools/list")
                self.assertEqual(listed.status_code, 200, listed.text)
                catalogue = listed.json()["result"]["tools"]
                self.assertEqual({item["name"] for item in catalogue}, {
                    "analysis_tools", "analysis_call", "analysis_start", "analysis_poll", "analysis_cancel"})
                self.assertEqual(len(catalogue), 5)
                for engine in ("ghidra", "radare2"):
                    described = await frame("tools/call", "analysis_tools", {"engine":engine})
                    self.assertEqual(described.status_code, 200, described.text)
                    self.assertFalse(described.json()["result"].get("isError"), described.text)
                    native = described.json()["result"]["structuredContent"]
                    self.assertEqual(native["engine"], engine)
                    self.assertTrue(native["tools"])
                    if engine == "radare2":
                        self.assertEqual({item["name"] for item in native["tools"]}, TOOLS)
                    else:
                        public = {item["name"]:item for item in native["tools"]}
                        print("Ghidra actual tools:", sorted(public), flush=True)
                        safe = next((name for name in ("list_projects", "list_active_programs", "check_connection")
                            if name in public and not public[name]["inputSchema"].get("required")), None)
                        self.assertIsNotNone(safe, "An actual bounded Ghidra project/runtime read is required")
                        checked = await frame("tools/call", "analysis_call",
                            {"engine":"ghidra", "tool":safe, "arguments":{}})
                        self.assertEqual(checked.status_code, 200, checked.text)
                        self.assertFalse(checked.json()["result"].get("isError"), checked.text)
                        self.assertTrue(checked.json()["result"].get("content"), checked.text)
                        print("Ghidra actual native read:", safe, checked.json()["result"], flush=True)
                        def unpack(value):
                            while isinstance(value, dict) and set(value) == {"result"}:
                                value = value["result"]
                            return json.loads(value) if isinstance(value, str) else value

                        async def ghidra_call(name, args, *, pause=False):
                            started = await frame("tools/call", "analysis_start",
                                {"engine":"ghidra", "tool":name, "arguments":args},
                                **({"expires_at":int(time.time())+2} if pause else {}))
                            self.assertEqual(started.status_code, 200, started.text)
                            state = started.json()["result"]["structuredContent"]
                            operation_id = state["operation_id"]
                            if pause:
                                await asyncio.sleep(3)
                                states = []
                                for status_file in Path("/proc").glob("[0-9]*/status"):
                                    try:
                                        facts = dict(line.split(":",1) for line in status_file.read_text().splitlines() if ":" in line)
                                    except (FileNotFoundError, ProcessLookupError):
                                        continue
                                    if 1000 in map(int, facts["Uid"].split()) and facts["State"].strip()[0] not in {"Z", "X"}:
                                        states.append(facts["State"].strip()[0])
                                self.assertTrue(states)
                                self.assertTrue(all(value in {"T", "t"} for value in states), states)
                                wrong = await frame("tools/call", "analysis_poll", {"operation_id":operation_id}, actor_uuid=uuid4())
                                self.assertTrue(wrong.json()["result"].get("isError"), wrong.text)
                            for _ in range(180):
                                polled = await frame("tools/call", "analysis_poll", {"operation_id":operation_id})
                                self.assertEqual(polled.status_code, 200, polled.text)
                                result = polled.json()["result"]
                                self.assertFalse(result.get("isError"), result)
                                state = result["structuredContent"]
                                if state["state"] != "running":
                                    break
                                await asyncio.sleep(0.5)
                            self.assertEqual(state["state"], "completed", state)
                            self.assertFalse(state["result"].get("isError"), state)
                            return unpack(state["result"]["structuredContent"])

                        gh_project = await ghidra_call("create_project", {"name":"native-async-acceptance"})
                        project_id = gh_project["project_id"]
                        code = bytes([184, 7, 0, 0, 0, 195])
                        tiny = (b"\x7fELF\x02\x01\x01"+bytes(9)
                            + struct.pack("<HHIQQQIHHHHHH",2,62,1,0x400078,64,0,0,64,56,1,0,0,0)
                            + struct.pack("<IIQQQQQQ",1,5,0,0x400000,0x400000,126,126,0x1000)+code)
                        self.assertEqual(len(tiny),126)
                        stage = await ghidra_call("artifact_stage_begin", {"project_id":project_id,
                            "name":"native-async.elf", "size_bytes":len(tiny), "sha256":hashlib.sha256(tiny).hexdigest()})
                        stage_id = stage["stage_id"]
                        await ghidra_call("artifact_stage_write", {"project_id":project_id,"stage_id":stage_id,
                            "offset":0,"data_base64":base64.b64encode(tiny).decode()})
                        staged = await ghidra_call("artifact_stage_finish", {"project_id":project_id,"stage_id":stage_id})
                        imported = await ghidra_call("import_file", {"project_id":project_id,
                            "file_path":staged["path"],"auto_analyze":True},pause=True)
                        print("Ghidra async import:",imported,flush=True)
                        decompiled = await ghidra_call("get_high_level_behavior_view", {"project_id":project_id,
                            "action":"00400078","program":"native-async.elf","timeout":60})
                        self.assertIn("7",json.dumps(decompiled))
                        print("Ghidra async decompile:",decompiled,flush=True)
                        await ghidra_call("artifact_stage_cancel", {"project_id":project_id,"stage_id":stage_id})
                        await ghidra_call("delete_project", {"project_id":project_id})
                self.assertTrue(all(isinstance(item.get("inputSchema"), dict) for item in catalogue))

                # Verify the actual separate native child identity, not an env flag.
                execution = []
                for path in Path("/proc").iterdir():
                    if not path.name.isdigit():
                        continue
                    try:
                        status = dict(line.split(":", 1) for line in (path/"status").read_text().splitlines() if ":" in line)
                    except (FileNotFoundError, ProcessLookupError):
                        continue
                    if int(status["Uid"].split()[0]) == 1000:
                        execution.append(status)
                self.assertTrue(execution)
                self.assertTrue(all(int(status["CapEff"].strip(), 16) == 0 and status["NoNewPrivs"].strip() == "1"
                                    for status in execution))

                self.assertEqual((await tool("radare2_list_binaries"))["binaries"], [])
                pending = await tool("radare2_import_start", {"name":"native-true.elf", "sha256":digest, "size":len(elf)})
                upload = pending["upload_id"]
                self.assertEqual(pending["chunk_bytes"], 12288)
                for offset in range(0, len(elf), pending["chunk_bytes"]):
                    chunk = elf[offset:offset+pending["chunk_bytes"]]
                    acknowledged = await tool("radare2_import_chunk", {"upload_id":upload, "offset":offset,
                        "content_base64":base64.b64encode(chunk).decode()})
                    self.assertEqual(acknowledged["offset"], offset+len(chunk))
                committed = await tool("radare2_import_finish", {"upload_id":upload})
                self.assertEqual((committed["sha256"], committed["size"]), (digest, len(elf)))
                binary = committed["binary_id"]
                self.assertEqual((await tool("radare2_list_binaries"))["binaries"], [committed])

                info = await tool("radare2_binary_info", {"binary_id":binary})
                self.assertEqual(info["result"]["bin"]["bintype"], "elf")
                self.assertIn(info["result"]["bin"]["bits"], {32, 64})
                self.assertTrue(info["result"]["bin"]["arch"])
                functions = await tool("radare2_functions", {"binary_id":binary, "limit":100})
                self.assertGreater(functions["total"], 0)
                self.assertTrue(functions["items"])
                function = next((item for item in functions["items"] if item.get("indegree", 0) > 0), None)
                self.assertIsNotNone(function, "Real ELF analysis must discover an inbound function reference")
                address = hex(function["addr"])
                disassembly = await tool("radare2_disassemble", {"binary_id":binary, "address":address, "count":8})
                self.assertTrue(disassembly["result"])
                self.assertTrue(all(isinstance(item.get("addr"), int) and item.get("opcode")
                                    for item in disassembly["result"]))
                strings = await tool("radare2_strings", {"binary_id":binary, "limit":20})
                self.assertGreater(strings["total"], 0)
                self.assertTrue(any(item.get("string") for item in strings["items"]))
                xrefs = await tool("radare2_xrefs", {"binary_id":binary, "address":address})
                self.assertIsInstance(xrefs["result"], list)
                self.assertTrue(xrefs["result"], "The selected function has a real incoming static reference")

                await tool("radare2_import_start", {"name":"../escape", "sha256":digest, "size":len(elf)}, error=True)
                await tool("radare2_binary_info", {"binary_id":"/etc/passwd"}, error=True)
                await tool("radare2_binary_info", {"binary_id":str(uuid4())}, error=True)
                await tool("radare2_disassemble", {"binary_id":binary, "address":"0x0;!id", "count":8}, error=True)
                unknown = await frame("tools/call", "radare2_arbitrary_command", {"command":"!id"})
                self.assertEqual(unknown.status_code, 200, unknown.text)
                self.assertTrue(unknown.json()["result"].get("isError"))
                await tool("radare2_arbitrary_command", {"command":"!id"}, error=True)
                wrong_engine = await frame("tools/call", "analysis_call",
                    {"engine":"unknown", "tool":"radare2_list_binaries", "arguments":{}})
                self.assertEqual(wrong_engine.status_code, 200, wrong_engine.text)
                self.assertTrue(wrong_engine.json()["result"].get("isError"))
                for changes in ({"workspace_uuid":uuid4()}, {"project_uuid":uuid4()}, {"module":"terminal"},
                                {"expires_at":int(time.time())-1}):
                    denied = await frame("tools/list", **changes)
                    self.assertEqual(denied.status_code, 403, denied.text)
                self.assertEqual((await tool("radare2_list_binaries"))["binaries"], [committed])

                # An exact-length upload with a wrong digest is never published.
                bad = await tool("radare2_import_start", {"name":"bad-hash.elf", "sha256":"0"*64, "size":4})
                await tool("radare2_import_chunk", {"upload_id":bad["upload_id"], "offset":0,
                    "content_base64":base64.b64encode(elf[:4]).decode()})
                await tool("radare2_import_finish", {"upload_id":bad["upload_id"]}, error=True)
                await tool("radare2_import_abort", {"upload_id":bad["upload_id"]})
                self.assertEqual((await tool("radare2_list_binaries"))["binaries"], [committed])
                deleted = await tool("radare2_delete_binary", {"binary_id":binary})
                self.assertEqual(deleted["state"], "deleted")
                self.assertEqual((await tool("radare2_list_binaries"))["binaries"], [])


if __name__ == "__main__":
    unittest.main()
