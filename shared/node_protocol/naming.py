"""DNS-safe deterministic worker identity shared by placement and routing."""

import hashlib
from uuid import UUID


def worker_name(node: UUID | str, placement: UUID | str, fingerprint: str) -> str:
    identity = (str(node) + ":" + str(placement) + ":" + fingerprint).encode("ascii")
    return "briareus-" + hashlib.sha256(b"briareus:worker-name\0" + identity).hexdigest()[:48]
