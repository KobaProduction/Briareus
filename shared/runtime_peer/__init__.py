"""Private RPC exports, loaded only when a transport consumer requests them.

Event window policy and projections can be imported without JWT/crypto drivers.
Transport consumers keep the existing public import paths and dependency errors.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .transport import (
        PeerClient,
        PeerIdentity,
        PeerRejected,
        PeerVerifier,
        VerifiedOwnerReply,
        canonical_json,
    )

__all__ = [
    "PeerClient",
    "PeerIdentity",
    "PeerRejected",
    "PeerVerifier",
    "VerifiedOwnerReply",
    "canonical_json",
]


def __getattr__(name: str) -> object:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from . import transport

    match name:
        case "PeerClient":
            return transport.PeerClient
        case "PeerIdentity":
            return transport.PeerIdentity
        case "PeerRejected":
            return transport.PeerRejected
        case "PeerVerifier":
            return transport.PeerVerifier
        case "VerifiedOwnerReply":
            return transport.VerifiedOwnerReply
        case _:
            return transport.canonical_json
