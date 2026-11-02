"""Typed references for identical existing Authorization constructor assignments."""

from service_runtime._reference_bindings import _KeyBinding as _KeyBinding
from service_runtime._reference_bindings import _OwnerBinding as _OwnerBinding


class _AuthLedgerBinding[AuthT, LedgerT]:
    def __init__(self, auth: AuthT, ledger: LedgerT) -> None:
        self.auth = auth
        self.ledger = ledger
