"""The lazy public API still exposes the original authenticated transport types."""

import runtime_peer
from runtime_peer import (
    PeerClient,
    PeerIdentity,
    PeerRejected,
    PeerVerifier,
    canonical_json,
    transport,
)


def test_public_exports_retain_transport_identity() -> None:
    assert PeerClient is transport.PeerClient
    assert PeerIdentity is transport.PeerIdentity
    assert PeerRejected is transport.PeerRejected
    assert PeerVerifier is transport.PeerVerifier
    assert canonical_json is transport.canonical_json


def test_unknown_export_remains_an_attribute_error() -> None:
    try:
        runtime_peer.__getattr__("not_a_public_export")
    except AttributeError as error:
        assert "not_a_public_export" in str(error)
    else:
        raise AssertionError("Unknown runtime_peer export was accepted")
