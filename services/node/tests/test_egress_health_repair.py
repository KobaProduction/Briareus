"""Bounded health and exact-owned companion replacement contract."""
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from node_agent.docker_engine import labels,network_name,EngineFailure
from node_agent.egress_runtime import companion_config,companion_name,ensure_egress
from node_agent.runtime_profiles import ROLE_LABEL,EGRESS_MEMORY,EGRESS_CPU,EGRESS_PIDS


class EgressHealthRepairTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.spec=SimpleNamespace(node_uuid=uuid4(),id=uuid4(),fingerprint='f'*64,container_name='briareus-'+'a'*48)
        self.desired=companion_config(self.spec,'registry.example/node@sha256:'+'b'*64)

    def test_probe_uses_only_socket_and_rejects_non_200(self):
        health=self.desired['Healthcheck']
        self.assertEqual(health['Timeout'],8_000_000_000)
        self.assertEqual(health['StartPeriod'],20_000_000_000)
        self.assertNotIn('urllib',health['Test'][-1])
        host=self.desired['HostConfig']
        self.assertEqual((host['Memory'],host['NanoCpus'],host['PidsLimit']),
            (EGRESS_MEMORY,EGRESS_CPU*1_000_000,EGRESS_PIDS))
        for status,success in ((b'HTTP/1.1 200 OK\r\n',True),(b'HTTP/1.1 503 Busy\r\n',False),(b'garbage 200\r\n',False)):
            sent=[]
            connection=SimpleNamespace(sendall=sent.append,makefile=lambda mode:io.BytesIO(status),close=lambda:None)
            with patch('socket.create_connection',return_value=connection) as connect:
                if success:exec(health['Test'][-1],{})
                else:
                    with self.assertRaises(AssertionError):exec(health['Test'][-1],{})
                connect.assert_called_once_with(('127.0.0.1',8080),2)
                self.assertEqual(sent,[b'GET /health/ready HTTP/1.0\r\nHost: localhost\r\n\r\n'])

    def engine(self,*,foreign=False,current=False):
        spec=self.spec;desired=self.desired;requests=[]
        expected={**labels(spec),ROLE_LABEL:'egress'}
        existing={'Name':'/'+companion_name(spec.container_name),'Config':{'Labels':dict(expected),
            'Healthcheck':desired['Healthcheck'] if current else {'Test':['CMD','old-probe']}},'NetworkSettings':{'Networks':{}}}
        if foreign:existing['Config']['Labels'][ROLE_LABEL]='main'
        class Engine:
            utility_image=desired['Image']
            async def containers(self,node):
                return [{'Id':'old-helper','Names':[existing['Name']],'Labels':expected}]
            async def inspect(self,container):
                if container=='old-helper':return existing
                return {'Name':existing['Name'],'Config':desired,'NetworkSettings':{'Networks':{}}}
            async def request(self,method,path,**kwargs):
                requests.append((method,path,kwargs))
                if path=='/networks':
                    value=[{'Name':network_name(spec)+'-egress','Internal':False,'Driver':'bridge','Labels':{
                        **{key:expected[key] for key in ('io.briareus.node','io.briareus.deployment')},ROLE_LABEL:'egress'}}]
                elif path=='/containers/create':value={'Id':'new-helper'}
                else:value={}
                return SimpleNamespace(json=lambda:value)
        return Engine(),requests

    async def test_only_owned_outdated_helper_is_replaced_with_same_alias_and_quota(self):
        engine,requests=self.engine()
        self.assertEqual(await ensure_egress(engine,self.spec),'new-helper')
        self.assertIn(('POST','/containers/old-helper/stop'),[(method,path) for method,path,_ in requests])
        self.assertIn(('DELETE','/containers/old-helper'),[(method,path) for method,path,_ in requests])
        create=next(data['json'] for method,path,data in requests if path=='/containers/create')
        self.assertEqual(create,self.desired)
        self.assertEqual(create['NetworkingConfig']['EndpointsConfig'][network_name(self.spec)]['Aliases'],['module-egress','web-egress'])
        self.assertFalse(any(self.spec.container_name in path for _,path,_ in requests))

    async def test_foreign_inspect_labels_refuse_removal_and_current_helper_is_preserved(self):
        engine,requests=self.engine(foreign=True)
        with self.assertRaises(EngineFailure):await ensure_egress(engine,self.spec)
        self.assertFalse(any(method in {'POST','DELETE'} for method,_,_ in requests))
        engine,requests=self.engine(current=True)
        self.assertEqual(await ensure_egress(engine,self.spec),'old-helper')
        self.assertFalse(any(method=='DELETE' or path=='/containers/create' for method,path,_ in requests))
