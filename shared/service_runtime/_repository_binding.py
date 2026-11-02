"""Typed reference for the existing public repository constructor contract."""


class _RepositoryBinding[RepositoryT]:
    def __init__(self, repository: RepositoryT) -> None:
        self.repository = repository
