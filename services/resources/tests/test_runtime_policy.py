"""Runtime overrides are independent from short authority leases."""
import os
import unittest
from unittest.mock import patch
from uuid import uuid4
from node_protocol.models import RuntimePolicy,RuntimePolicyOverrides,ModuleConfiguration,Deployment
from node_protocol.grpc_codec import encode_deployment,decode_deployment
from projects.runtime_policy import resolve_policy
from common.owner_migrations import owner_config

class RuntimePolicyTests(unittest.TestCase):
    def test_defaults_inheritance_and_explicit_disable(self):
        policy,sources=resolve_policy()
        self.assertIsNone(policy.execution_timeout_seconds);self.assertEqual(policy.web_max_tabs,10)
        policy,sources=resolve_policy({"execution_timeout_seconds":90,"web_max_tabs":4,"terminal_idle_seconds":30},{"execution_timeout_seconds":None,"web_max_tabs":12})
        self.assertIsNone(policy.execution_timeout_seconds);self.assertEqual(policy.web_max_tabs,12)
        self.assertEqual(policy.terminal_idle_seconds,30);self.assertEqual(sources["execution_timeout_seconds"],"node")
        self.assertEqual(sources["terminal_idle_seconds"],"server")
    def test_override_serialization_preserves_inheritance(self):
        from pydantic import BaseModel
        class Wrapper(BaseModel):
            policy:RuntimePolicyOverrides
        wire=Wrapper(policy=RuntimePolicyOverrides(web_max_tabs=None)).model_dump(mode="json")
        self.assertEqual(wire,{"policy":{"web_max_tabs":None}})

    def test_typed_protobuf_preserves_nullable_policy(self):
        spec=Deployment(id=uuid4(),node_uuid=uuid4(),project_uuid=uuid4(),release={"module":"svc","lifecycle":"sessionful","image":"localhost:5500/svc@sha256:"+"a"*64},limits={"memory_bytes":1024**3,"cpu_millis":1000,"pids":128},
            configuration=ModuleConfiguration(runtime_policy=RuntimePolicy(web_max_tabs=None,execution_timeout_seconds=7)))
        decoded=decode_deployment(encode_deployment(spec))
        self.assertEqual(decoded,spec);self.assertEqual(decoded.fingerprint,spec.fingerprint)
    def test_missing_policy_keeps_legacy_wire(self):
        self.assertNotIn("runtime_policy",ModuleConfiguration().model_dump())
    def test_reviewed_additive_migration_graph(self):
        self.assertEqual(owner_config("resources").get_main_option("script_location").replace("\\","/").split("/")[-1],"migrations")


class RuntimePolicyRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_node_command_fields_and_server_read_route(self):
        import json
        from contextlib import asynccontextmanager
        from datetime import UTC,datetime,timedelta
        from types import SimpleNamespace
        from fastapi import Request
        from projects.node_management import NodeCommand,NodeRegistration,node_router
        from cryptography.fernet import Fernet
        self.assertTrue({"policy_scope","policy_values","expected_policy_sequence"}<=set(NodeCommand.model_fields))
        self.assertFalse({"policy_scope","policy_values","expected_policy_sequence"}&set(NodeRegistration.model_fields))
        actor,project=uuid4(),uuid4()
        expiry=datetime.now(UTC)+timedelta(seconds=15)
        command=NodeCommand(issuer="https://provider.example",subject="fixture",actor_uuid=actor,project_uuid=project,
            operation_uuid=uuid4(),identity_expires_at=expiry,action="runtime_policy_get",policy_scope="server")
        async def call(path,wire):
            return 200,{"issuer":wire["issuer"],"subject":wire["subject"],"actor_uuid":str(actor),"project_uuid":str(project),
                "role":"operator","permissions":["use_resources"],"expires_at":expiry.isoformat()}
        class Tx:
            async def get(self,*args):return None
            async def scalar(self,*args):return None
        class DB:
            @asynccontextmanager
            async def transaction(self):yield Tx()
        router=node_router(platform=SimpleNamespace(call=call),resolve_database=lambda:DB(),cipher=Fernet(Fernet.generate_key()))
        try:
            reply=await router.routes[0].endpoint(command,Request({"type":"http","briareus.service_peer":"briareus:control-panel-api"}))
            value=json.loads(reply.body)["runtime_policy"]
            self.assertEqual(value["sequence"],0);self.assertIsNone(value["effective"]["execution_timeout_seconds"])
            self.assertEqual(value["effective"]["web_max_tabs"],10)
        finally:await router.node_placements.close()
