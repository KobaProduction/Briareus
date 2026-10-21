"""Packaged native SDK/ELF workflow in a disposable rootless placement.

Run against the BUILT image with only this test directory mounted read-only;
do not override its packaged runtime/source. Fixture signatures exercise the
Node/SDK boundary and are deliberately not Rauthy/Cedar or external acceptance.
No uploaded binary is executed: the real pinned radare2 parses a copied ELF.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
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
from radare2_hand.node_server import create_app

TOOLS = frozenset({"radare2_import_start", "radare2_import_chunk", "radare2_import_finish", "radare2_import_abort",
    "radare2_list_binaries", "radare2_delete_binary", "radare2_binary_info", "radare2_functions",
    "radare2_disassemble", "radare2_strings", "radare2_xrefs"})


class NodeRadare2Tests(unittest.IsolatedAsyncioTestCase):
    async def test_packaged_native_elf_analysis_and_private_storage_boundary(self):
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
            release=ModuleRelease(module="radare2", image="registry.example/radare2@sha256:" + "a"*64,
                                  lifecycle="sessionful"),
            limits=ResourceLimits(memory_bytes=512*1024**2, cpu_millis=500, pids=64),
            workspace=WorkspaceMount(id=storage), effect_verify_key=key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode())
        app = create_app(spec)
        bearer = "Bearer native-radare2-fixture-not-provider-identity"
        async with app.app.router.lifespan_context(app.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),
                base_url="http://"+spec.container_name+".radare2") as client:
                sequence = 0

                async def frame(method, tool=None, arguments=None, **changes):
                    nonlocal sequence
                    sequence += 1
                    wire = {"jsonrpc":"2.0", "id":sequence, "method":method}
                    if tool is not None:
                        wire["params"] = {"name":tool, "arguments":arguments or {}}
                    body = json.dumps(wire, separators=(",", ":")).encode()
                    self.assertLessEqual(len(body), 32768)
                    parsed, now = parse_request("radare2", body), int(time.time())
                    values = dict(module="radare2", node_uuid=node, placement_uuid=placement,
                        project_uuid=project, workspace_uuid=storage, actor_uuid=actor,
                        agent_session_uuid=session, request_uuid=uuid4(), grant_revision=1,
                        fingerprint=spec.fingerprint, body_digest=hashlib.sha256(body).hexdigest(),
                        bearer_digest=hashlib.sha256(bearer.encode()).hexdigest(),
                        arguments_digest=hashlib.sha256(canonical(parsed.arguments)).hexdigest(),
                        method=parsed.method, tool=parsed.tool, resource_id=resource_id("radare2", node, project, storage),
                        issued_at=now, expires_at=now+5)
                    values.update(changes)
                    return await client.post("/mcp", content=body, headers={"content-type":"application/json",
                        "authorization":bearer, "accept":"application/json, text/event-stream",
                        "mcp-protocol-version":"2025-11-25",
                        "x-briareus-node-permit":sign_permit(NodeEffectPermit(**values), key)})

                async def tool(name, arguments=None, *, error=False):
                    response = await frame("tools/call", name, arguments)
                    self.assertEqual(response.status_code, 200, response.text)
                    result = response.json()["result"]
                    self.assertEqual(bool(result.get("isError")), error, result)
                    return result.get("structuredContent")

                listed = await frame("tools/list")
                self.assertEqual(listed.status_code, 200, listed.text)
                catalogue = listed.json()["result"]["tools"]
                self.assertEqual({item["name"] for item in catalogue}, TOOLS)
                self.assertEqual(len(catalogue), 11)
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
