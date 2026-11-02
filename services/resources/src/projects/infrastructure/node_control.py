"""Core-to-node service channel with independently pinned node identity."""

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import grpc
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from node_protocol import Deployment, NodeRecord, NodeScope
from node_protocol.control import ControlCommand
from node_protocol.domain.observations import NodeEvent, NodeReply
from node_protocol.grpc_codec import decode_reply, encode_command
from node_protocol.grpc_control import NodeControlClient
from node_protocol.grpc_events import NodeEventVerifier
from node_protocol.replies import NodeReplyVerifier
from node_protocol.runtime import rootless_budget
from projects._node_persistence import NodeRow
from projects.application.node_control import NodeControlAction
from projects.application.node_control import NodeUnavailable as NodeUnavailable
from projects.domain.node_control import NodeOrigin
from projects.infrastructure.node_setup import NodeJournalSetup, NodeSetupResult


def node_record(row: NodeRow) -> NodeRecord:
    return NodeRecord(
        id=row.id,
        name=row.name,
        scope=NodeScope.model_validate({"kind": row.scope, "owner_uuid": row.owner_uuid}),
        budget=row.budget,
        enabled=row.enabled,
        created_at=row.created_at,
    )


class NodeControl:
    def __init__(
        self,
        signing_key: Ed25519PrivateKey,
        origins: frozenset[str],
        gateway_verify_key: str | None = None,
        journal_setup: NodeJournalSetup | None = None,
    ) -> None:
        if not isinstance(signing_key, Ed25519PrivateKey):
            raise ValueError("Resources Ed25519 service key required")
        self.key, self.origins = signing_key, origins
        self.gateway_verify_key = gateway_verify_key
        self.journal_setup = journal_setup
        self.channels: dict[str, grpc.aio.Channel] = {}
        self.public_key = (
            signing_key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        )

    @classmethod
    @lru_cache(maxsize=1)
    def from_environment(cls) -> "NodeControl":
        origins = json.loads(os.environ.get("BRIAREUS_NODE_ORIGINS", "[]"))
        if (
            not isinstance(origins, list)
            or len(origins) > 100
            or any(
                not isinstance(origin, str) or NodeOrigin(origin).value != origin
                for origin in origins
            )
        ):
            raise ValueError("Explicit canonical node origins required")
        key = serialization.load_pem_private_key(
            Path(os.environ["RESOURCES_SIGNING_KEY_FILE"]).read_bytes(), password=None
        )
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Resources Ed25519 service key required")
        gateway = None
        if os.environ.get("RESOURCES_GATEWAY_VERIFY_KEY_FILE"):
            public = serialization.load_pem_public_key(
                Path(os.environ["RESOURCES_GATEWAY_VERIFY_KEY_FILE"]).read_bytes()
            )
            if not isinstance(public, Ed25519PublicKey):
                raise ValueError("Pinned Gateway Ed25519 public identity required")
            gateway = public.public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            ).decode()
        return cls(
            key,
            frozenset(origin for origin in origins if isinstance(origin, str)),
            gateway_verify_key=gateway,
            journal_setup=NodeJournalSetup.from_environment(os.environ),
        )

    async def close(self) -> None:
        await asyncio.gather(*(channel.close() for channel in self.channels.values()))
        self.channels.clear()

    def channel(self, endpoint: str) -> grpc.aio.Channel:
        if endpoint not in self.origins:
            raise NodeUnavailable("Node origin is not approved for service control")
        if endpoint not in self.channels:
            roots = None
            if os.environ.get("BRIAREUS_NODE_CA_FILE"):
                roots = Path(os.environ["BRIAREUS_NODE_CA_FILE"]).read_bytes()
            target = endpoint.removeprefix("https://") + ":443"
            options: list[tuple[str, str | int]] = [
                ("grpc.max_send_message_length", 65536),
                ("grpc.max_receive_message_length", 1048576),
                ("grpc.enable_retries", 0),
            ]
            if os.environ.get("BRIAREUS_LOCAL_NODE_DIAL"):
                if (
                    os.environ.get("BRIAREUS_LOCAL_TESTING") != "1"
                    or endpoint != "https://127.0.0.2"
                    or os.environ["BRIAREUS_LOCAL_NODE_DIAL"] != "local-node-tls:443"
                    or roots is None
                ):
                    raise NodeUnavailable("Local node dial override rejected")
                target = "local-node-tls:443"
                options.extend(
                    [
                        ("grpc.ssl_target_name_override", "127.0.0.2"),
                        ("grpc.default_authority", "127.0.0.2"),
                    ]
                )
            self.channels[endpoint] = grpc.aio.secure_channel(
                target, grpc.ssl_channel_credentials(root_certificates=roots), options=options
            )
        return self.channels[endpoint]

    def setup(self, row: NodeRow) -> NodeSetupResult:
        return self.setup_target(
            node_record(row), runtime_uid=row.runtime_uid, endpoint=row.endpoint
        )

    def setup_target(
        self, record: NodeRecord, *, runtime_uid: int, endpoint: str
    ) -> NodeSetupResult:
        if self.gateway_verify_key is None:
            raise ValueError("Gateway public identity must be configured before node installation")
        if self.journal_setup is None:
            raise ValueError(
                "Explicit Resources journal target and public CA required before installation"
            )
        return NodeSetupResult(
            node_record=record,
            core_verify_key=self.public_key,
            gateway_verify_key=self.gateway_verify_key,
            runtime_uid=runtime_uid,
            runtime_user="briareus-" + str(record.id)[:8],
            runtime_gid=runtime_uid,
            rootless_budget=rootless_budget(record.budget),
            endpoint=endpoint,
            origin_approved=endpoint in self.origins,
            journal=self.journal_setup,
        )

    async def watch(
        self,
        *,
        endpoint: str,
        public_key: str,
        node_uuid: UUID,
        operation_uuid: UUID,
        sequence: int,
        after_event: int = 0,
    ) -> AsyncIterator[NodeEvent]:
        now = int(time.time())
        command = ControlCommand(
            node_uuid=node_uuid,
            operation_uuid=operation_uuid,
            action="watch",
            sequence=sequence,
            issued_at=now,
            expires_at=now + 60,
            after_event=after_event,
        )
        verifier = NodeEventVerifier(public_key.encode(), command)
        stub = NodeControlClient(self.channel(endpoint))
        call = stub.Watch(
            encode_command(command, self.key.sign(command.signing_bytes())), timeout=61
        )
        try:
            async for event in call:
                yield verifier.verify(event)
        except (grpc.RpcError, ValueError):
            raise NodeUnavailable(
                "Node event stream interrupted; resume from verified cursor"
            ) from None
        finally:
            call.cancel()

    async def call(
        self,
        *,
        endpoint: str,
        public_key: str,
        node_uuid: UUID,
        operation_uuid: UUID,
        sequence: int,
        action: NodeControlAction = "inventory",
        record: NodeRecord | None = None,
        deployment: Deployment | None = None,
    ) -> NodeReply:
        if endpoint not in self.origins:
            raise NodeUnavailable("Node origin is not approved for service control")
        verifier = NodeReplyVerifier(public_key.encode())
        now = int(time.time())
        command = ControlCommand(
            node_uuid=node_uuid,
            operation_uuid=operation_uuid,
            action=action,
            sequence=sequence,
            issued_at=now,
            expires_at=now + 20,
            node_record=record,
            deployment=deployment,
        )
        try:
            stub = NodeControlClient(self.channel(endpoint))
            method = {
                "inventory": stub.Inventory,
                "configure": stub.Configure,
                "apply": stub.Apply,
                "status": stub.Operation,
            }[action]
            response = await method(
                encode_command(command, self.key.sign(command.signing_bytes())), timeout=6
            )
            status = response.proof.status_code
            payload = verifier.verify(command, status, decode_reply(response))
            if status not in {200, 202}:
                raise ValueError("Node did not accept the command")
            return payload
        except (grpc.RpcError, TimeoutError, ValueError):
            raise NodeUnavailable("Authenticated node control unavailable") from None
