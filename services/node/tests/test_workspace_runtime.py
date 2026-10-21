"""Named-volume control effects, cleanup and refusal of host-backed drivers."""
import unittest
from uuid import uuid4

import httpx

from node_protocol import WorkspaceMount
from node_agent.docker_engine import EngineFailure
from node_agent.workspace_runtime import prepare_workspace, recover_workspace_helpers, volume_name, workspace_labels, initializer_config
from test_reconciliation import fixture


class Engine:
    def __init__(self):
        self.utility_image="registry.example/node@sha256:"+"a"*64
        self.workspace_cleanup_uncertain=False
        self.volume=None
        self.helper=None
        self.actions=[]
        self.exit_code=0

    async def inspect(self, container):
        return {"Config":{"Labels":self.helper["Labels"]},"State":self.helper["state"]} if self.helper else None

    async def request(self, method, path, **kwargs):
        self.actions.append((method,path,kwargs))
        status=200
        if method=="GET" and path.startswith("/volumes/"):
            value=self.volume or {}
            status=200 if self.volume else 404
        elif path=="/volumes/create":
            self.volume={**kwargs["json"],"Options":{}}
            value=self.volume
            status=201
        elif method=="GET" and path=="/containers/json":
            value=[self.helper] if self.helper else []
        elif path=="/containers/create":
            self.helper={"Id":"b"*64,"Labels":kwargs["json"]["Labels"],
                "Names":["/"+kwargs["params"]["name"]],"state":{"Status":"created","Running":False}}
            self.helper["Labels"]={"org.opencontainers.image.source":"https://example.test/node",**self.helper["Labels"]}
            value={"Id":self.helper["Id"]}
            status=201
        elif path.endswith("/start"):
            self.helper["state"]={"Status":"running","Running":True}
            value={}
        elif path.endswith("/wait"):
            self.helper["state"]={"Status":"exited","Running":False}
            value={"StatusCode":self.exit_code}
        elif path.endswith("/stop"):
            self.helper["state"]={"Status":"exited","Running":False}
            value={}
        elif method=="DELETE" and path.startswith("/containers/"):
            self.helper=None
            value={}
            status=204
        else:
            raise AssertionError("Unexpected control effect: "+path)
        return httpx.Response(status,json=value)


class WorkspaceRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def spec(self):
        _,spec=fixture()
        return spec.model_copy(update={"workspace":WorkspaceMount(id=uuid4())})

    async def test_initialize_and_failure_cleanup_preserve_volume(self):
        engine,spec=Engine(),self.spec()
        await prepare_workspace(engine,spec)
        self.assertEqual(engine.volume["Name"],volume_name(spec))
        self.assertIsNone(engine.helper)
        engine.exit_code=1
        with self.assertRaises(EngineFailure):
            await prepare_workspace(engine,spec)
        self.assertIsNone(engine.helper)
        self.assertEqual(engine.volume["Name"],volume_name(spec))
        self.assertFalse(any(method=="DELETE" and path.startswith("/volumes") for method,path,_ in engine.actions))

    async def test_host_backed_or_foreign_volume_is_not_adopted(self):
        spec=self.spec()
        for overrides in [{"Options":{"device":"/","type":"none","o":"bind"}},{"Labels":{}},{"Driver":"nfs"}]:
            engine=Engine()
            engine.volume={"Name":volume_name(spec),"Driver":"local","Labels":workspace_labels(spec),"Options":{},**overrides}
            with self.assertRaises(EngineFailure):
                await prepare_workspace(engine,spec)
            self.assertTrue(all(method=="GET" for method,_,_ in engine.actions))

    async def test_helper_accepts_image_metadata_but_rejects_extra_ownership(self):
        engine,spec=Engine(),self.spec()
        config=initializer_config(spec,engine.utility_image)
        engine.helper={"Id":"b"*64,"Labels":{**config["Labels"],"io.briareus.foreign":"other"},
            "Names":["/briareus-workspace-init-"+spec.workspace.id.hex],
            "state":{"Status":"exited","Running":False}}
        with self.assertRaises(EngineFailure):
            await prepare_workspace(engine,spec)
        self.assertFalse(any(method in {"DELETE","POST"} and path.startswith("/containers/")
            for method,path,_ in engine.actions))

    async def test_restart_reaps_only_verified_scoped_initializer(self):
        engine,spec=Engine(),self.spec()
        config=initializer_config(spec,engine.utility_image)
        engine.helper={"Id":"b"*64,"Labels":config["Labels"],
            "Names":["/briareus-workspace-init-"+spec.workspace.id.hex],
            "state":{"Status":"running","Running":True}}
        await recover_workspace_helpers(engine,spec.node_uuid)
        self.assertIsNone(engine.helper)
        mutations=[path for method,path,_ in engine.actions if method!="GET"]
        self.assertEqual(mutations,["/containers/"+"b"*64+"/stop","/containers/"+"b"*64])
