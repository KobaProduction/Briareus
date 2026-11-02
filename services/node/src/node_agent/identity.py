"""Persistent node service key. Only its public half leaves the node."""

import base64
import hashlib
import os
import stat
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from node_protocol.control import ControlCommand, ReplyProof, canonical
from node_protocol.domain.observations import NodeReply
from node_protocol.reply_wire import NodeReplyWire, reply_payload


class NodeIdentity:
    def __init__(self, path: Path) -> None:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            generated_key = Ed25519PrivateKey.generate()
            with os.fdopen(fd, "wb") as stream:
                stream.write(
                    generated_key.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption(),
                    )
                )
                stream.flush()
                os.fsync(stream.fileno())
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("Node key must be an owner-private regular file")
            key = serialization.load_pem_private_key(stream.read(4096), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Node service identity requires Ed25519")
        self.key = key
        self.public_key = (
            key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        )

    def reply(
        self,
        command: ControlCommand,
        status: int,
        payload: NodeReply,
    ) -> NodeReplyWire:
        result = reply_payload(payload)
        now = int(time.time())
        proof = ReplyProof(
            node_uuid=command.node_uuid,
            operation_uuid=command.operation_uuid,
            request_digest=hashlib.sha256(command.signing_bytes()).hexdigest(),
            response_digest=hashlib.sha256(
                canonical(result.model_dump(mode="json", exclude_unset=True))
            ).hexdigest(),
            status_code=status,
            issued_at=now,
            expires_at=now + 15,
        )
        return NodeReplyWire(
            result=result,
            proof=proof,
            signature=base64.b64encode(self.key.sign(proof.signing_bytes())).decode(),
        )


if __name__ == "__main__":
    path = Path("/var/lib/briareus-node/node.key")
    if not path.is_file():
        raise SystemExit("Start the node controller before reading its public identity")
    print(NodeIdentity(path).public_key, end="")
