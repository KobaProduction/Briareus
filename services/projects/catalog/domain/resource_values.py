"""Framework-free Catalog invariants with each layout's nominal value bindings."""

import re
from collections.abc import Callable
from enum import StrEnum
from uuid import UUID


class _ResourceOwnerProperties[Scope: StrEnum, TeamIdentifier, ProjectIdentifier]:
    __slots__ = ()

    scope: Scope
    owner_id: UUID
    _team_scope: Scope
    _project_scope: Scope
    _team_factory: Callable[[UUID], TeamIdentifier]
    _project_factory: Callable[[UUID], ProjectIdentifier]

    @property
    def team_id(self) -> TeamIdentifier | None:
        return self._team_factory(self.owner_id) if self.scope is self._team_scope else None

    @property
    def project_id(self) -> ProjectIdentifier | None:
        return self._project_factory(self.owner_id) if self.scope is self._project_scope else None


class _ResourceOrigin[Scope: StrEnum, TeamIdentifier, ProjectIdentifier]:
    __slots__ = ()

    owner: _ResourceOwnerProperties[Scope, TeamIdentifier, ProjectIdentifier]

    @property
    def origin(self) -> Scope:
        return self.owner.scope


class _ResourceNames:
    def __init__(self, invalid_input: type[Exception]) -> None:
        self._invalid_input = invalid_input

    def canonical_alias(self, value: str) -> tuple[str, str]:
        alias = value.strip()
        if not 1 <= len(alias) <= 128:
            raise self._invalid_input("alias must contain 1-128 characters")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", alias, flags=re.ASCII):
            raise self._invalid_input("alias must start with a letter and use letters/digits/_.-")
        return alias, alias.casefold()

    def canonical_variable_name(self, value: str) -> str:
        key = value.strip().upper()
        if len(key) > 128 or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key, flags=re.ASCII):
            raise self._invalid_input("variable name must be an identifier up to 128 characters")
        return key
