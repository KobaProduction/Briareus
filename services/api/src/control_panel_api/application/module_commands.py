"""Application-visible selectors of an already validated human Hand command."""

from typing import Protocol
from uuid import UUID


class HumanToolCommand(Protocol):
    @property
    def project_uuid(self) -> UUID: ...

    @property
    def operation_uuid(self) -> UUID: ...

    @property
    def tool(self) -> str: ...

    @property
    def preparation_engine(self) -> str | None: ...
