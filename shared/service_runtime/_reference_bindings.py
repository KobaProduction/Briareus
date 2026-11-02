"""Existing typed peer, owner, key and verifier reference assignments only."""


class _PeerBinding[PeerT]:
    def __init__(self, peer: PeerT) -> None:
        self._peer = peer


class _OwnerBinding[OwnerT]:
    def __init__(self, owner: OwnerT) -> None:
        self._owner = owner


class _KeyBinding[KeyT]:
    def __init__(self, key: KeyT) -> None:
        self.key = key


class _VerifierBinding[VerifierT]:
    def __init__(self, verifier: VerifierT) -> None:
        self._verifier = verifier


class _ClientBinding[ClientT]:
    def __init__(self, client: ClientT) -> None:
        self._client = client
