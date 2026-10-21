"""Core-to-node service channel with independently pinned node identity."""
import asyncio
import base64
import json
import os
import time
from functools import lru_cache
from pathlib import Path

import grpc
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from node_protocol import NodeBudget, NodeRecord, NodeScope
from node_protocol.control import ControlCommand
from node_protocol.replies import NodeReplyVerifier
from node_protocol.runtime import rootless_budget
from node_protocol import node_pb2_grpc
from node_protocol.grpc_codec import encode_command, decode_reply
from node_protocol.grpc_events import NodeEventVerifier


class NodeUnavailable(ValueError):
    pass


def node_record(row):
    return NodeRecord(id=row.id, name=row.name,
        scope=NodeScope(kind=row.scope, owner_uuid=row.owner_uuid),
        budget=NodeBudget.model_validate(row.budget), enabled=row.enabled, created_at=row.created_at)


class NodeControl:
    def __init__(self, signing_key: Ed25519PrivateKey, origins: frozenset[str], gateway_verify_key=None):
        if not isinstance(signing_key, Ed25519PrivateKey):
            raise ValueError("Resources Ed25519 service key required")
        self.key, self.origins = signing_key, origins
        self.gateway_verify_key = gateway_verify_key
        self.channels = {}
        self.public_key = signing_key.public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    @classmethod
    @lru_cache(maxsize=1)
    def from_environment(cls):
        origins = json.loads(os.environ.get("BRIAREUS_NODE_ORIGINS", "[]"))
        from projects.node_management import NodeRegistration
        if (not isinstance(origins, list) or len(origins) > 100
            or any(not isinstance(origin, str) or NodeRegistration.endpoint_valid(origin) != origin
                   for origin in origins)):
            raise ValueError("Explicit canonical node origins required")
        key = serialization.load_pem_private_key(
            Path(os.environ["RESOURCES_SIGNING_KEY_FILE"]).read_bytes(), password=None)
        gateway = None
        if os.environ.get("RESOURCES_GATEWAY_VERIFY_KEY_FILE"):
            public = serialization.load_pem_public_key(Path(os.environ["RESOURCES_GATEWAY_VERIFY_KEY_FILE"]).read_bytes())
            if not isinstance(public, Ed25519PublicKey):
                raise ValueError("Pinned Gateway Ed25519 public identity required")
            gateway = public.public_bytes(serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        return cls(key, frozenset(origins), gateway_verify_key=gateway)

    async def close(self):
        await asyncio.gather(*(channel.close() for channel in self.channels.values()))
        self.channels.clear()

    def channel(self, endpoint):
        if endpoint not in self.origins:
            raise NodeUnavailable("Node origin is not approved for service control")
        if endpoint not in self.channels:
            roots = None
            if os.environ.get("BRIAREUS_NODE_CA_FILE"):
                roots = Path(os.environ["BRIAREUS_NODE_CA_FILE"]).read_bytes()
            target = endpoint.removeprefix("https://") + ":443"
            options = [("grpc.max_send_message_length",65536),("grpc.max_receive_message_length",1048576),
                ("grpc.enable_retries",0)]
            if os.environ.get("BRIAREUS_LOCAL_NODE_DIAL"):
                if (os.environ.get("BRIAREUS_LOCAL_TESTING")!="1" or endpoint!="https://127.0.0.2"
                    or os.environ["BRIAREUS_LOCAL_NODE_DIAL"]!="local-node-tls:443" or roots is None):
                    raise NodeUnavailable("Local node dial override rejected")
                target="local-node-tls:443"
                options.extend([("grpc.ssl_target_name_override","127.0.0.2"),("grpc.default_authority","127.0.0.2")])
            self.channels[endpoint]=grpc.aio.secure_channel(target,grpc.ssl_channel_credentials(root_certificates=roots),options=options)
        return self.channels[endpoint]

    def setup(self, row):
        if self.gateway_verify_key is None:
            raise ValueError("Gateway public identity must be configured before node installation")
        record = node_record(row)
        execution = rootless_budget(record.budget).model_dump()
        return {"node_record": record.model_dump(mode="json"), "core_verify_key": self.public_key,
                "gateway_verify_key": self.gateway_verify_key,
                "runtime_uid": row.runtime_uid, "runtime_user": "briareus-" + str(row.id)[:8],
                "runtime_gid": row.runtime_uid, "rootless_budget": execution,
                "endpoint": row.endpoint, "origin_approved": row.endpoint in self.origins}

    async def watch(self, *, endpoint, public_key, node_uuid, operation_uuid, sequence, after_event=0):
        now=int(time.time())
        command=ControlCommand(node_uuid=node_uuid,operation_uuid=operation_uuid,action="watch",sequence=sequence,
            issued_at=now,expires_at=now+60,after_event=after_event)
        verifier=NodeEventVerifier(public_key.encode(),command)
        stub=node_pb2_grpc.NodeControlStub(self.channel(endpoint))
        call=stub.Watch(encode_command(command,self.key.sign(command.signing_bytes())),timeout=61)
        try:
            async for event in call:
                yield verifier.verify(event)
        except (grpc.RpcError,ValueError):
            raise NodeUnavailable("Node event stream interrupted; resume from verified cursor") from None
        finally:
            call.cancel()

    async def call(self, *, endpoint, public_key, node_uuid, operation_uuid, sequence,
                   action="inventory", record=None, deployment=None):
        if endpoint not in self.origins:
            raise NodeUnavailable("Node origin is not approved for service control")
        verifier = NodeReplyVerifier(public_key.encode())
        now = int(time.time())
        command = ControlCommand(node_uuid=node_uuid, operation_uuid=operation_uuid, action=action,
            sequence=sequence, issued_at=now, expires_at=now + 20, node_record=record, deployment=deployment)
        try:
            stub=node_pb2_grpc.NodeControlStub(self.channel(endpoint))
            method=getattr(stub,{"inventory":"Inventory","configure":"Configure","apply":"Apply","status":"Operation"}[action])
            response=await method(encode_command(command,self.key.sign(command.signing_bytes())),timeout=6)
            status=response.proof.status_code
            payload=verifier.verify(command,status,decode_reply(response))
            if status not in {200,202}:
                raise ValueError("Node did not accept the command")
            return payload
        except (grpc.RpcError, TimeoutError, ValueError):
            raise NodeUnavailable("Authenticated node control unavailable") from None
