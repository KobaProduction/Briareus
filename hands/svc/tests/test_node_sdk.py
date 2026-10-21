"""Packaged SDK/private-context fixture; not Rauthy or provider acceptance."""
import asyncio
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
from svc_hand.node_server import create_app

svc = "svc"
ACCOUNT_TOOLS = ["github_accounts","accounts"]


class PackagedNodeSDKTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalogue_and_signed_private_project_context(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(os.statvfs("/").f_flag & os.ST_RDONLY)
        self.assertEqual({p.name for p in Path("/sys/class/net").iterdir()}, {"lo"})
        mapping = Path("/proc/self/uid_map").read_text().splitlines()[0].split()
        self.assertNotEqual(int(mapping[1]), 0)
        key = Ed25519PrivateKey.generate()
        node, project, storage, placement, actor, session = (uuid4() for _ in range(6))
        spec = Deployment(id=placement, node_uuid=node, project_uuid=project,
            release=ModuleRelease(module=svc, image="registry.example/"+svc+"@sha256:"+"a"*64,
                lifecycle="sessionful"), limits=ResourceLimits(memory_bytes=512*1024**2,cpu_millis=500,pids=96),
            workspace=WorkspaceMount(id=storage), effect_verify_key=key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode())
        app = create_app(spec)
        bearer = "Bearer fixture-not-rauthy"
        async with app.app.router.lifespan_context(app.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),
                    base_url="http://"+spec.container_name+"."+svc) as client:
                async def ready():
                    async with asyncio.timeout(125):
                        while (await client.get("/health/ready")).status_code != 200:
                            await asyncio.sleep(.1)

                def request(method, tool=None, *, context=True, **changes):
                    frame = {"jsonrpc":"2.0","id":1,"method":method}
                    if tool is not None:
                        frame["params"]={"name":tool,"arguments":{}}
                    body = json.dumps(frame,separators=(",",":")).encode()
                    parsed, now = parse_request(svc, body), int(time.time())
                    raw = b'{"accounts":[],"policies":{}}'
                    values = dict(module=svc,node_uuid=node,placement_uuid=placement,project_uuid=project,
                        workspace_uuid=storage,actor_uuid=actor,agent_session_uuid=session,request_uuid=uuid4(),
                        grant_revision=1,fingerprint=spec.fingerprint,body_digest=hashlib.sha256(body).hexdigest(),
                        bearer_digest=hashlib.sha256(bearer.encode()).hexdigest(),
                        arguments_digest=hashlib.sha256(canonical(parsed.arguments)).hexdigest(),
                        method=parsed.method,tool=parsed.tool,resource_id=resource_id(svc,node,project,storage),
                        issued_at=now,expires_at=now+5,context_digest=hashlib.sha256(raw).hexdigest() if context else "")
                    values.update(changes)
                    headers={"content-type":"application/json","authorization":bearer,
                        "accept":"application/json, text/event-stream","mcp-protocol-version":"2025-11-25",
                        "x-briareus-node-permit":sign_permit(NodeEffectPermit(**values),key)}
                    if context:
                        headers["x-briareus-invocation-context"]=base64.b64encode(raw).decode()
                    return body,headers

                async def send(pair):
                    return await client.post("/mcp",content=pair[0],headers=pair[1])

                listed = await send(request("tools/list",context=False))
                self.assertEqual(listed.status_code,200,listed.text)
                catalogue = listed.json()["result"]["tools"]
                self.assertEqual(len(catalogue), 143)
                self.assertTrue(all(isinstance(t.get("inputSchema"),dict) for t in catalogue))
                self.assertTrue(set(ACCOUNT_TOOLS).issubset({t["name"] for t in catalogue}))
                self.assertTrue(all("x-briareus-invocation-context" not in t["inputSchema"].get("properties",{})
                                    for t in catalogue))
                children = []
                for p in Path("/proc").iterdir():
                    if not p.name.isdigit():
                        continue
                    try:
                        status=dict(line.split(":",1) for line in (p/"status").read_text().splitlines() if ":" in line)
                    except (FileNotFoundError,ProcessLookupError):
                        continue
                    if int(status["Uid"].split()[0])==1000:
                        children.append(status)
                self.assertTrue(children)
                self.assertTrue(all(int(s["CapEff"].strip(),16)==0 and s["NoNewPrivs"].strip()=="1" for s in children))
                self.assertFalse(Path("/var/run/docker.sock").exists())
                for name in ACCOUNT_TOOLS:
                    response = await send(request("tools/call",name))
                    self.assertEqual(response.status_code,200,response.text)
                    result=response.json()["result"]
                    self.assertFalse(result.get("isError"),result)
                    payload=result["structuredContent"]
                    self.assertEqual(payload.get("accounts",payload.get("sources")),[])
                    self.assertEqual(payload["count"],0)
                    self.assertEqual((await client.get("/health/ready")).status_code,200,
                        "Same-identity calls must not trigger a full child warmup")
                    self.assertNotIn("credential",response.text)
                    self.assertNotIn("policies",response.text)
                    self.assertNotIn("context_digest",response.text)
                # Expiry freezes the same unprivileged process; a fresh exact
                # permit resumes it without rebuilding the module.
                child_pid = children[0]["Pid"].strip()
                await asyncio.sleep(5.2)
                status_path = Path("/proc") / child_pid / "status"
                paused = dict(line.split(":",1) for line in status_path.read_text().splitlines() if ":" in line)
                self.assertEqual(paused["State"].strip()[0], "T")
                resumed = await send(request("tools/call",ACCOUNT_TOOLS[0]))
                self.assertEqual(resumed.status_code,200,resumed.text)
                self.assertFalse(resumed.json()["result"].get("isError"))
                # A different actor gets a new process, never the previous
                # principal's provider state or a silently replayed call.
                new_actor = uuid4()
                changed = await send(request("tools/call",ACCOUNT_TOOLS[0],actor_uuid=new_actor))
                self.assertEqual(changed.status_code,200,changed.text)
                self.assertTrue(changed.json()["result"].get("isError"))
                await ready()
                self.assertFalse(status_path.exists())
                fresh = await send(request("tools/call",ACCOUNT_TOOLS[0],actor_uuid=new_actor))
                self.assertEqual(fresh.status_code,200,fresh.text)
                self.assertFalse(fresh.json()["result"].get("isError"))
                await ready()
                replay=request("tools/list",context=False)
                self.assertEqual((await send(replay)).status_code,200)
                self.assertEqual((await send(replay)).status_code,409)
                for change in ({"project_uuid":uuid4()},{"workspace_uuid":uuid4()},
                               {"expires_at":int(time.time())-1}):
                    denied=await send(request("tools/list",**change))
                    self.assertEqual(denied.status_code,403,denied.text)
                for mode in ("tamper","missing","unbound"):
                    body,headers=request("tools/list",context=mode!="unbound")
                    marker="private-context-must-not-reflect"
                    if mode=="missing":
                        del headers["x-briareus-invocation-context"]
                    else:
                        headers["x-briareus-invocation-context"]=base64.b64encode(
                            json.dumps({"accounts":[],"marker":marker}).encode()).decode()
                    denied=await send((body,headers))
                    self.assertEqual(denied.status_code,403,denied.text)
                    self.assertNotIn(marker,denied.text)
                await ready()
                no_context=await send(request("tools/call",ACCOUNT_TOOLS[0],context=False))
                self.assertEqual(no_context.status_code,200,no_context.text)
                self.assertTrue(no_context.json()["result"].get("isError"))
