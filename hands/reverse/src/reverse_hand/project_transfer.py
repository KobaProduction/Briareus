"""Project-volume bytes to private Ghidra via fixed loopback; staged fallback."""
import asyncio
import base64
import hashlib
import os
from pathlib import Path
import stat
import tempfile
from contextlib import contextmanager, suppress
import httpx

class UnsupportedUpload(Exception):
    """Explicit older-engine endpoint absence permits staged fallback."""

MAX_BYTES=256*1024**2

@contextmanager
def source_snapshot(relative,root=Path("/workspace/project"),staging=Path("/project-data/ghidra/cache")):
    if not isinstance(relative,str) or not relative or "\\" in relative or "\0" in relative:
        raise ValueError("Relative project file required")
    parts=relative.split("/")
    if any(part in {"",".",".."} for part in parts):raise ValueError("Relative project file required")
    flags=os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK
    fd=os.open(root,flags|os.O_DIRECTORY)
    original=None
    try:
        device=os.fstat(fd).st_dev
        for index,part in enumerate(parts):
            child=os.open(part,flags|(os.O_DIRECTORY if index<len(parts)-1 else 0),dir_fd=fd)
            os.close(fd);fd=child
            info=os.fstat(fd)
            if info.st_uid!=1000 or info.st_gid!=1000 or info.st_mode&0o022 or info.st_dev!=device:
                raise ValueError("Unsafe project file owner")
        original=os.fstat(fd)
        if not stat.S_ISREG(original.st_mode) or original.st_nlink!=1 or original.st_size>MAX_BYTES:
            raise ValueError("Bounded regular project file required")
        with tempfile.TemporaryDirectory(prefix="transfer-",dir=staging) as temporary:
            target=Path(temporary)/parts[-1]
            digest=hashlib.sha256();total=0
            with target.open("xb") as output:
                while block:=os.read(fd,1024**2):
                    total+=len(block)
                    if total>MAX_BYTES:raise ValueError("Project file exceeds transfer limit")
                    digest.update(block);output.write(block)
            after=os.fstat(fd)
            if (original.st_size,original.st_mtime_ns,original.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                raise ValueError("Project file changed during transfer")
            yield target,total,digest.hexdigest()
    finally:os.close(fd)


def register_transfer(mcp,provider):
    @mcp.tool()
    async def upload_project_file(project_id:str,workspace_path:str):
        """Copy a file from this placement's read-only shared project workspace into Analysis.

        Call via analysis_start(engine="ghidra",tool="upload_project_file",arguments=...).
        Returns artifact path for the normal import tool. Direct raw bytes use
        private loopback; older engines use staged chunks. No host paths/URLs.
        """
        if os.environ.get("BRIAREUS_PROJECT_TRANSFER")!="1":raise ValueError("Attach this project's workspace first")
        with source_snapshot(workspace_path) as (source,size,digest):
            async def chunks():
                with source.open("rb") as stream:
                    while block:=stream.read(1024**2):yield block;await asyncio.sleep(0)
            try:
                async with httpx.AsyncClient(timeout=None,trust_env=False,follow_redirects=False) as client:
                    reply=await client.post("http://127.0.0.1:8081/internal/artifacts/upload",
                        params={"project_id":project_id,"name":source.name},
                        headers={"X-Koba-Proxy-Origin":"analysis","X-Artifact-Size":str(size),
                            "X-Artifact-SHA256":digest,"Content-Type":"application/octet-stream"},content=chunks())
                if reply.status_code in {404,405,501}:
                    raise UnsupportedUpload()
                reply.raise_for_status();value=reply.json()
                if value.get("sha256")!=digest or value.get("size_bytes")!=size or not isinstance(value.get("path"),str):
                    raise ValueError("Verified artifact receipt required")
                return {**value,"workspace_path":workspace_path}
            except UnsupportedUpload:pass
            begun=await provider._call("artifact_stage_begin",{"project_id":project_id,"name":source.name,"size_bytes":size,"sha256":digest})
            stage=begun["stage_id"]
            try:
                offset=0
                with source.open("rb") as stream:
                    while block:=stream.read(24000):
                        written=await provider._call("artifact_stage_write",{"project_id":project_id,"stage_id":stage,
                            "offset":offset,"data_base64":base64.b64encode(block).decode()})
                        if written.get("next_offset")!=offset+len(block):raise ValueError("Invalid stage offset")
                        offset+=len(block)
                result=await provider._call("artifact_stage_finish",{"project_id":project_id,"stage_id":stage})
                return {**result,"workspace_path":workspace_path,"size_bytes":size,"sha256":digest,"transfer_method":"mcp_base64"}
            except BaseException:
                with suppress(Exception):await provider._call("artifact_stage_cancel",{"project_id":project_id,"stage_id":stage})
                raise
