"""Typed routing proof for local adapter tests; never submitted to a running Node."""

import time
from uuid import uuid4

from node_protocol import Deployment
from node_protocol.forward import ForwardProof


def routing_proof(spec: Deployment) -> ForwardProof:
    now = int(time.time())
    return ForwardProof(
        node_uuid=spec.node_uuid,
        placement_uuid=spec.id,
        project_uuid=spec.project_uuid,
        agent_session_uuid=uuid4(),
        request_uuid=uuid4(),
        grant_revision=1,
        module=spec.release.module,
        fingerprint=spec.fingerprint,
        port=spec.release.port,
        body_digest="a" * 64,
        bearer_digest="b" * 64,
        issued_at=now,
        expires_at=now + 15,
    )
