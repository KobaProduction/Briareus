"""Typed account references for existing Admin application use cases."""


class _AccountsBinding[AccountsT]:
    def __init__(self, accounts: AccountsT) -> None:
        self._accounts = accounts
