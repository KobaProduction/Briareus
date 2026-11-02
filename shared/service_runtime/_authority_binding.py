"""Pure reference binding with an explicit optional-authority default."""


class _AuthorityBinding[AuthorityT]:
    def __init__(self, authority: AuthorityT) -> None:
        self._authority = authority


class _OptionalAuthorityBinding[AuthorityT](_AuthorityBinding[AuthorityT | None]):
    def __init__(self, authority: AuthorityT | None = None) -> None:
        super().__init__(authority)
