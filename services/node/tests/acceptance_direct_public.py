"""Disposable daemon/Terminal network gate; deliberately no Core authority claim.

Run from an immutable Node utility with only a trusted control-runner Docker
UDS mount. The packaged Terminal child receives no engine socket or secrets.
"""
import asyncio
import json
import os
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from node_protocol import Deployment
from node_agent.docker_engine import network_name,labels
from node_agent.network_policy import NetworkPolicy,helper_config
from node_agent.network_policy_runtime import prepare_direct_network,_json_log


WORKER = r'''
import asyncio,json,os,shlex,sys,uuid
from pathlib import Path
from node_protocol import Deployment
from hand_runtime.process_lease import ProcessLease
from terminal_hand.network_guard import read_attestation
from terminal_hand.worker_server import TerminalSupervisor,require_supervisor_isolation

async def main():
 spec=Deployment.model_validate_json(os.environ['BRIAREUS_DEPLOYMENT'])
 path=Path('/terminal-link/network-policy.json')
 descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(descriptor,'w') as stream:stream.write(os.environ['AUDIT_NETWORK_ATTESTATION'])
 facts=read_attestation(spec)
 require_supervisor_isolation(facts)
 supervisor=TerminalSupervisor(spec.project_uuid,None,Path('/var/lib/terminal-supervisor'),execution_uid=1000,
  workspace_root='/project-data',prewarm=True,process_lease=ProcessLease(1000),network_facts=facts)
 try:
  await supervisor.warmup()
  async def call(tool,arguments):
   request={'id':uuid.uuid4().hex,'tool':tool,'arguments':arguments}
   supervisor.child.stdin.write((json.dumps(request)+'\n').encode());await supervisor.child.stdin.drain()
   reply=json.loads(await asyncio.wait_for(supervisor.child.stdout.readline(),90))
   assert reply.get('id')==request['id'] and 'result' in reply,reply
   return reply['result']['structuredContent']
  await call('workspace_create',{'workspace_id':'network-audit'})
  probe=r"""
import json,os,socket
from pathlib import Path
facts=json.loads(os.environ['AUDIT_ROUTING_FACTS'])
fields=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert os.geteuid()==1000 and int(fields['CapEff'].strip(),16)==0 and fields['NoNewPrivs'].strip()=='1'
assert not Path('/var/run/docker.sock').exists() and not Path('/audit-engine.sock').exists()
assert not any(os.environ.get(key) for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'))
addresses=socket.getaddrinfo('example.com',443,socket.AF_INET,socket.SOCK_STREAM)
assert addresses
with socket.create_connection(addresses[0][4],timeout=8):pass
results={'uid':os.geteuid(),'dns':'passed','public_tcp':'passed','denied':{}}
targets={'node_core':('172.25.80.1',5500),'bridge_gateway':(facts['gateway'],80),
 'private':('10.0.0.1',443),'metadata':('169.254.169.254',80),'explicit_public_control':('1.1.1.1',443)}
for name,address in targets.items():
 try:
  connection=socket.create_connection(address,timeout=2);connection.close()
 except OSError:results['denied'][name]=True
 else:raise AssertionError('Unexpected reachable protected destination: '+name)
print(json.dumps(results))
"""
  # Only public routing facts enter the actual UID1000 tool environment.
  command='/app/.venv/bin/python -c '+shlex.quote(probe)
  result=await call('terminal_exec',{'workspace_id':'network-audit','command':command,
   'env':{'AUDIT_ROUTING_FACTS':json.dumps(facts)},'timeout_seconds':40,'max_output_bytes':8192})
  assert result.get('exit_code')==0,result
  print(json.dumps({'stage':'actual_terminal_tool','result':result}),flush=True)
 finally:await supervisor.close()
asyncio.run(main())
'''


class FixtureEngine:
    def __init__(self,image):
        self.utility_image=image
        self.control_addresses=('1.1.1.1', '172.25.80.1')
        self.network_policy_cleanup_uncertain=False
        self.client=httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds='/audit-engine.sock'),
            base_url='http://audit-engine/v1.51',timeout=60,trust_env=False)

    async def request(self,method,path,*,accepted=(200,),**kwargs):
        response=await self.client.request(method,path,**kwargs)
        if response.status_code not in accepted:raise RuntimeError(f'Fixture engine operation {path} status {response.status_code}')
        if method=='POST' and path.endswith('/wait') and response.json().get('StatusCode')!=0:
            identifier=path.split('/')[2]
            failed=await self.client.get(f'/containers/{identifier}/logs',params={'stdout':'true','stderr':'true'})
            print('HELPER_FAILURE_LOG',repr(failed.content[:16000]),flush=True)
        return response

    async def inspect(self,container):
        response=await self.request('GET',f'/containers/{container}/json',accepted=(200,404))
        return response.json() if response.status_code==200 else None


async def main():
    utility=os.environ['AUDIT_UTILITY_IMAGE'];terminal=os.environ['AUDIT_TERMINAL_IMAGE']
    engine=FixtureEngine(utility)
    public=Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    spec=Deployment.model_validate({'id':str(uuid4()),'node_uuid':str(uuid4()),'project_uuid':str(uuid4()),
        'release':{'module':'terminal','image':terminal,'lifecycle':'sessionful'},
        'limits':{'memory_bytes':256*1024**2,'cpu_millis':500,'pids':128},
        'workspace':{'id':str(uuid4()),'read_only':False},'effect_verify_key':public,
        'configuration':{'network':{'profile':'public'}}})
    worker=None;policy=None
    try:
        attestation=await prepare_direct_network(engine,spec)
        policy=NetworkPolicy(str(spec.node_uuid),str(spec.id),attestation['bridge'],attestation['subnet'],engine.control_addresses)
        print(json.dumps({'stage':'policy_readback','attestation':attestation}),flush=True)
        if os.environ.get('AUDIT_POLICY_ONLY')!='1':
            config={'Image':terminal,'User':'0:0','Cmd':['/app/.venv/bin/python','-u','-c',WORKER],
                'Labels':labels(spec),'Env':['PYTHONPATH=/app/src','BRIAREUS_DEPLOYMENT='+spec.model_dump_json(),
                    'AUDIT_NETWORK_ATTESTATION='+json.dumps(attestation)],
                'WorkingDir':'/app/src','HostConfig':{'NetworkMode':network_name(spec)+'-public','ReadonlyRootfs':True,
                    'CapDrop':['ALL'],'CapAdd':['SETUID','SETGID','KILL'],'SecurityOpt':['no-new-privileges:true'],
                    'Memory':256*1024**2,'MemorySwap':256*1024**2,'NanoCpus':500_000_000,'PidsLimit':128,
                    'Tmpfs':{'/project-data':'rw,nosuid,nodev,uid=1000,gid=1000,mode=0700,size=32m',
                        '/terminal-link':'rw,nosuid,nodev,mode=0700,size=1m','/var/lib/terminal-supervisor':'rw,nosuid,nodev,mode=0700,size=8m',
                        '/home/agent':'rw,nosuid,nodev,uid=1000,gid=1000,mode=0700,size=32m','/tmp':'rw,nosuid,nodev,mode=1777,size=32m'}}}
            worker=(await engine.request('POST','/containers/create',accepted=(201,),params={'name':spec.container_name},json=config)).json()['Id']
            await engine.request('POST',f'/containers/{worker}/start',accepted=(204,))
            outcome=(await engine.request('POST',f'/containers/{worker}/wait',params={'condition':'not-running'})).json()
            output=(await engine.request('GET',f'/containers/{worker}/logs',params={'stdout':'true','stderr':'true'})).content
            # Retain raw multiplexed diagnostic output for a native failure report.
            print('WORKER_LOG',repr(output[:20000]),flush=True)
            assert outcome.get('StatusCode')==0,outcome
            print(json.dumps({'outcome':'passed','scope':'daemon-helper-and-native-Terminal-network-only'}),flush=True)
    finally:
        if worker is not None:
            await engine.request('DELETE',f'/containers/{worker}',accepted=(204,404),params={'force':'true'})
        # A bootstrap may have created chains before a later readback failure.
        network=await engine.request('GET','/networks/'+network_name(spec)+'-public',accepted=(200,404))
        if network.status_code==200:
            value=network.json()
            assert value['Labels'].get('io.briareus.node')==str(spec.node_uuid)
            assert value['Labels'].get('io.briareus.deployment')==str(spec.id)
            if policy is None:
                policy=NetworkPolicy(str(spec.node_uuid),str(spec.id),'br-'+value['Id'][:12],value['IPAM']['Config'][0]['Subnet'],engine.control_addresses)
            config=helper_config(policy,utility,'remove')
            cleanup=(await engine.request('POST','/containers/create',accepted=(201,),json=config)).json()['Id']
            try:
                await engine.request('POST',f'/containers/{cleanup}/start',accepted=(204,))
                result=(await engine.request('POST',f'/containers/{cleanup}/wait',params={'condition':'not-running'})).json()
                output=(await engine.request('GET',f'/containers/{cleanup}/logs',params={'stdout':'true','stderr':'true'})).content
                assert result.get('StatusCode')==0,repr(output)
                report=_json_log(output)
                assert report.get('state')=='removed' and report.get('fingerprint')==policy.fingerprint,report
                print(json.dumps({'stage':'policy_cleanup','result':report}),flush=True)
            finally:await engine.request('DELETE',f'/containers/{cleanup}',accepted=(204,404),params={'force':'true'})
            await engine.request('DELETE','/networks/'+value['Id'],accepted=(204,404))
        await engine.client.aclose()


if __name__=='__main__':asyncio.run(main())
