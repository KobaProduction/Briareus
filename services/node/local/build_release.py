"""Build from an exact local Git snapshot, publish locally, record immutable identity.

Uses a temporary Git index; main, the working checkout and user's index are unchanged.
No CI image build, public registry, secret build arguments or source task files.
"""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"shared"))
from node_protocol.catalog import ARTIFACTS


def run(args, *, env=None, data=None):
    value=subprocess.run(args,cwd=ROOT,env=env,input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if value.returncode:
        raise RuntimeError(value.stderr.decode(errors="replace")[-3000:])
    return value.stdout


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("module",choices=[*ARTIFACTS,"node"])
    args=parser.parse_args()
    if args.module=="node":
        inputs={"dockerfile":"services/node/Dockerfile","platform":"linux/amd64","paths":[
            "services/node/Dockerfile","services/node/Dockerfile.dockerignore","services/node/pyproject.toml",
            "services/node/uv.lock","services/node/src/**","shared/node_protocol/**","shared/gateway_runtime/**"]}
    else:
        definition=ARTIFACTS[args.module]
        if not definition.node_adapter:
            raise ValueError("An implemented node adapter is required for publication")
        inputs=definition.inputs
    installation=json.loads((ROOT/".local/briareus/secrets/node/installation.json").read_text())
    host=installation["registry_host"]
    paths=[path.removesuffix('/**') for path in inputs["paths"]]
    reference="refs/heads/codex/local-build-"+args.module
    with tempfile.TemporaryDirectory(prefix="briareus-release-") as directory:
        temporary=Path(directory)
        env=os.environ.copy()
        env["GIT_INDEX_FILE"]=str(temporary/"index")
        run(["git","read-tree","HEAD"],env=env)
        run(["git","add","-A","--",*paths],env=env)
        tree=run(["git","write-tree"],env=env).decode().strip()
        listing=run(["git","ls-tree","-rz",tree,"--",*paths])
        for entry in listing.split(b'\0'):
            if entry and not entry.startswith((b'100644 blob ',b'100755 blob ')):
                raise ValueError("Build inputs must be regular Git files")
        build_args=inputs.get("build_args",{})
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*",name) or not re.fullmatch(
            r"localhost:5500/briareus/[a-z0-9_-]+@sha256:[a-f0-9]{64}",value)
            for name,value in build_args.items()):
            raise ValueError("Only immutable approved local image build inputs are allowed")
        fingerprint_input=listing
        if build_args:
            fingerprint_input+=b'\0build_args\0'+json.dumps(build_args,sort_keys=True,separators=(",",":")).encode()
        fingerprint=hashlib.sha256(fingerprint_input).hexdigest()
        previous=subprocess.run(["git","rev-parse","--verify",reference],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        if previous.returncode==0 and run(["git","ls-tree","-rz",previous.stdout.decode().strip(),"--",*paths])==listing:
            commit=previous.stdout.decode().strip()
        else:
            commit=run(["git","-c","user.name=Briareus local build","-c","user.email=local-build@invalid",
                "commit-tree",tree,"-p","HEAD"],data=("Local build snapshot: "+args.module+"\n").encode()).decode().strip()
            run(["git","update-ref",reference,commit])
        context=temporary/"context"
        context.mkdir()
        archive=run(["git","archive",commit,"--",*paths])
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(context,filter="data")
        tag="localhost:5500/briareus/"+args.module+":local"
        metadata=temporary/"build-metadata.json"
        # Publish directly without unpacking a second copy into Desktop's image
        # store. The dedicated Node engine pulls this exact registry digest.
        build_command=["docker","buildx","build","--platform",inputs["platform"],"-t",tag,
            "--output","type=image,push=true,store=false,unpack=false","--metadata-file",str(metadata)]
        for name,value in sorted(build_args.items()):
            build_command += ["--build-arg",name+"="+value]
        run([*build_command,"-f",str(context/inputs["dockerfile"]),str(context)])
        digest=json.loads(metadata.read_text(encoding="utf-8")).get("containerimage.digest","")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}",digest):
            raise ValueError("Exact published image digest required")
        result={"id":str(uuid4()),"module":args.module,"source_commit":commit,"input_fingerprint":fingerprint,
            "platform":inputs["platform"],"image":host+":5500/briareus/"+args.module+"@"+digest}
        if build_args:
            result["build_args"]=build_args
        output=ROOT/".local/briareus/secrets/node/releases"
        output.mkdir(mode=0o700,exist_ok=True)
        (output/(args.module+".json")).write_text(json.dumps(result,indent=2),encoding="utf-8")
        print(json.dumps(result))


if __name__=="__main__":
    main()
