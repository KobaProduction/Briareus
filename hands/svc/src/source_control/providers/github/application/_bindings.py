"""Retain each GitHub use case's precisely typed dependency reference."""


class _ProviderBinding[Provider]:
    def __init__(self, provider: Provider) -> None:
        self.provider = provider


class _SourceBinding[Source]:
    def __init__(self, source: Source) -> None:
        self.source = source
