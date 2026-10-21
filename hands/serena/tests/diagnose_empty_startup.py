"""Disposable diagnostic ONLY: stderr visibility is intentionally overridden.

This is not a packaged acceptance pass. It creates no source file/project and
uses the original full run_node_app entry point with an empty tmpfs workspace.
"""
import asyncio
import json
import os
import signal
import socket
import threading
import time
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

BOOTSTRAP = r'''
import builtins,os,runpy
original=builtins.open
def diagnostic_open(file,*args,**kwargs):
 if file==os.devnull and args and args[0]=='w':return os.fdopen(os.dup(2),'w')
 return original(file,*args,**kwargs)
builtins.open=diagnostic_open
runpy.run_module('serena_hand.isolated_child',run_name='__main__')
'''
original_spawn=asyncio.create_subprocess_exec
async def spawn(*args,**kwargs):
    capture='serena_hand.isolated_child' in args
    if capture:
        args=(args[0],'-c',BOOTSTRAP)
        kwargs['stderr']=asyncio.subprocess.PIPE
    child=await original_spawn(*args,**kwargs)
    if capture:
        async def drain():
            remaining=16000
            while True:
                line=await child.stderr.readline()
                if not line:return
                if remaining>0:
                    print('DIAGNOSTIC_CHILD_STDERR',line[:remaining].decode(errors='replace'),flush=True)
                    remaining-=len(line)
        asyncio.create_task(drain())
    return child
asyncio.create_subprocess_exec=spawn

public=Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
os.environ['BRIAREUS_DEPLOYMENT']=json.dumps({'id':str(uuid4()),'node_uuid':str(uuid4()),'project_uuid':str(uuid4()),
    'release':{'module':'serena','image':os.environ['AUDIT_SERENA_IMAGE'],'lifecycle':'sessionful'},
    'limits':{'memory_bytes':1024**3,'cpu_millis':500,'pids':128},'effect_verify_key':public,
    'workspace':{'id':str(uuid4()),'read_only':False}})
ready=[]
def probe():
    deadline=time.monotonic()+185
    while time.monotonic()<deadline:
        try:
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(2)
                connection.connect('/serena-link/mcp.sock')
                connection.sendall(b'GET /health/ready HTTP/1.0\r\nHost: localhost\r\n\r\n')
                status=connection.makefile('rb').readline(128)
                if status.split(b' ',2)[1]==b'200':
                    ready.append(True)
                    print('DIAGNOSTIC_FULL_NODE_READY',flush=True)
                    os.kill(os.getpid(),signal.SIGTERM)
                    return
        except (OSError,IndexError):pass
        time.sleep(1)
    os.kill(os.getpid(),signal.SIGTERM)
threading.Thread(target=probe,daemon=True).start()
from hand_runtime.node_adapter import run_node_app
from serena_hand.node_server import create_app
run_node_app(create_app,'serena')
assert ready,'Diagnostic full startup never reached ready'
