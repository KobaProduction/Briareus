"""Opt-in real packaged Chrome transfers; fixture-only CDP seeds synthetic DOM.

No source overlay or Core credentials. Public example.com verifies real egress;
local synthetic form avoids sending fixture files to an external service.
"""
import asyncio
import json
import os
from pathlib import Path
import uuid
import httpx
from websockets.asyncio.client import connect
from web_hand.node_supervisor import WebSupervisor, require_supervisor_isolation


async def as_tool(code):
    process=await asyncio.create_subprocess_exec("/app/.venv/bin/python","-c",code,user=1000,group=1000,extra_groups=[],
        env={"PATH":"/usr/local/bin:/usr/bin:/bin"},stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    out,err=await process.communicate()
    assert process.returncode==0,err.decode()
    return out.decode().strip()


async def main():
    require_supervisor_isolation()
    print(await as_tool("from pathlib import Path; import os; a=Path('/browser');b=Path('/workspace/project');assert a.stat().st_dev!=b.stat().st_dev; (b/'fixture-upload.txt').write_text('fixture-upload-v1'); (b/'fixture-upload.txt').chmod(0o600); (a/'private-canary').write_text('private-canary-v1');(a/'private-canary').chmod(0o600); (b/'forbidden-cookie-link').symlink_to(a/'private-canary'); print('two-distinct-storage-mounts')"),flush=True)
    supervisor=WebSupervisor(project_workspace=True)
    try:
        await supervisor.start("b"*64)
        names={tool["name"] for tool in supervisor.metadata}
        assert len(names)>=25 and all("curl" not in name.lower() for name in names)
        async def call(name,arguments=None,error=False):
            request={"id":uuid.uuid4().hex,"tool":name,"arguments":arguments or {},"profile":str(supervisor.profile)}
            supervisor.child.stdin.write((json.dumps(request)+"\n").encode());await supervisor.child.stdin.drain()
            reply=json.loads(await asyncio.wait_for(supervisor.child.stdout.readline(),120))
            assert reply.get("id")==request["id"]
            result=reply.get("result",{})
            failed=bool(reply.get("error") or result.get("isError"))
            if failed and name == "local_browser_status":
                diagnostic = await call("local_browser_diagnostics")
                print(json.dumps({"chrome_failure_diagnostics":diagnostic}),flush=True)
            assert failed==error,reply
            print(json.dumps({"tool":name,"expected_error":error,"failed":failed}),flush=True)
            if error:return
            value=result.get("structuredContent")
            return value if value is not None else json.loads(result["content"][0]["text"])
        external=await call("external_status");assert external["enabled"] is False
        status=await call("local_browser_status");assert status["running"] and status["cdp_reachable"]
        page=await call("local_browser_open",{"url":"https://example.com"});assert page["http_status"]==200
        page_id=page["page_id"]
        snap=await call("local_browser_snapshot",{"page_id":page_id});assert "Example Domain" in json.dumps(snap)
        await call("local_browser_debug_target",{"page_id":page_id})
        async with httpx.AsyncClient(trust_env=False) as http:
            targets=(await http.get("http://127.0.0.1:9222/json/list")).json()
        target=next(item for item in targets if item.get("url","").startswith("https://example.com"))
        async with connect(target["webSocketDebuggerUrl"],proxy=None) as socket:
            command_id=0
            async def evaluate(expression):
                nonlocal command_id
                command_id+=1
                await socket.send(json.dumps({"id":command_id,"method":"Runtime.evaluate","params":{
                    "expression":expression,"returnByValue":True,"awaitPromise":True}}))
                while True:
                    response=json.loads(await socket.recv())
                    if response.get("id")==command_id:break
                assert "error" not in response and "exceptionDetails" not in response.get("result",{}),response
                return response["result"]["result"].get("value")
            html='<html><body><input id="upload" type="file"><a id="download" download="fixture.txt">Download fixture</a><script>document.getElementById("download").href=URL.createObjectURL(new Blob(["fixture-download-v1"],{type:"text/plain"}));</script></body></html>'
            await evaluate('document.open();document.write('+json.dumps(html)+');document.close();document.cookie="fixture_private_cookie=fixture-cookie-v1; path=/";true')
            snap=await call("local_browser_snapshot",{"page_id":page_id})
            upload=next(e["ref"] for e in snap["elements"] if e.get("type")=="file")
            download=next(e["ref"] for e in snap["elements"] if e.get("tag")=="a")
            await call("local_browser_upload",{"page_id":page_id,"ref":upload,"workspace_path":"forbidden-cookie-link"},error=True)
            await call("local_browser_upload",{"page_id":page_id,"ref":upload,"workspace_path":"../private-canary"},error=True)
            await call("local_browser_upload",{"page_id":page_id,"ref":upload,"workspace_path":"fixture-upload.txt"})
            text=await evaluate('document.querySelector("#upload").files[0].text()')
            assert text=="fixture-upload-v1",text
            downloaded=await call("local_browser_download",{"page_id":page_id,"ref":download,"workspace_path":"downloads/result.txt"})
            assert downloaded["path"]=="downloads/result.txt" and downloaded["size_bytes"]==19,downloaded
            await call("local_browser_screenshot",{"page_id":page_id,"workspace_path":"screenshots/result.png"})
            print(await as_tool("from pathlib import Path;import os; r=Path('/workspace/project');assert (r/'downloads/result.txt').read_text()=='fixture-download-v1';assert (r/'screenshots/result.png').read_bytes().startswith(bytes([137,80,78,71]));assert not list(r.rglob('Cookies'));assert not (r/'private-canary').exists();assert (Path('/browser')/'private-canary').read_text()=='private-canary-v1';print('shared-content-and-private-profile-separation-passed')"),flush=True)
        print(json.dumps({"outcome":"passed","scope":"packaged-browser-shared-transfers"}),flush=True)
    finally:
        await supervisor.stop()
        for name in ("memory.events","memory.peak","pids.events"):
            path=Path('/sys/fs/cgroup')/name
            if path.exists():print('CGROUP',name,path.read_text(),flush=True)

if __name__=="__main__":asyncio.run(main())
