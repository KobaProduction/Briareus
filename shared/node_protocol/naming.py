"""DNS-safe deterministic worker identity shared by placement and routing."""
import hashlib


def worker_name(node, placement, fingerprint):
    identity=(str(node)+":"+str(placement)+":"+fingerprint).encode("ascii")
    return "briareus-"+hashlib.sha256(b"briareus:worker-name\0"+identity).hexdigest()[:48]
