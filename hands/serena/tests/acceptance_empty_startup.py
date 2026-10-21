"""Full immutable Serena entry-point gate with no source/project in its workspace.

Native module startup only; no Core/Rauthy/Cedar acceptance is implied.
"""
import json
import os
import signal
import socket
import subprocess
import threading
import time
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

public=Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
os.environ['BRIAREUS_DEPLOYMENT']=json.dumps({'id':str(uuid4()),'node_uuid':str(uuid4()),'project_uuid':str(uuid4()),
    'release':{'module':'serena','image':os.environ['AUDIT_SERENA_IMAGE'],'lifecycle':'sessionful'},
    'limits':{'memory_bytes':1024**3,'cpu_millis':500,'pids':128},'effect_verify_key':public,
    'workspace':{'id':str(uuid4()),'read_only':False}})
outcome=[]
def probe():
    deadline=time.monotonic()+180
    try:
        while time.monotonic()<deadline:
            try:
                with socket.socket(socket.AF_UNIX) as connection:
                    connection.settimeout(2)
                    connection.connect('/serena-link/mcp.sock')
                    connection.sendall(b'GET /health/ready HTTP/1.0\r\nHost: localhost\r\n\r\n')
                    status=connection.makefile('rb').readline(128)
                    if status.split(b' ',2)[1]==b'200':
                        result=subprocess.run(['/usr/local/bin/python','-S','-c',
                            "from pathlib import Path; assert list(Path('/project-data').iterdir())==[]"],
                            user=1000,group=1000,extra_groups=[],capture_output=True,timeout=10)
                        assert result.returncode==0,'An empty workspace must not gain synthetic source/project files'
                        outcome.append(True)
                        print(json.dumps({'outcome':'passed','scope':'full-packaged-Serena-empty-startup',
                            'workspace_files':0,'fake_project':False}),flush=True)
                        return
            except (OSError,IndexError):pass
            time.sleep(1)
    finally:os.kill(os.getpid(),signal.SIGTERM)
threading.Thread(target=probe,daemon=True).start()
from hand_runtime.node_adapter import run_node_app
from serena_hand.node_server import create_app
run_node_app(create_app,'serena')
assert outcome,'Actual Serena empty-workspace startup did not become ready'
