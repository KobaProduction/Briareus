"""Verify reviewed owner-local metadata without owning migrations or SQL."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from common.domain.schema_contracts import OwnerSchemaRejected, TableSchema


@dataclass(frozen=True, slots=True)
class SchemaComparison:
    reviewed: TableSchema
    observed: TableSchema


@dataclass(frozen=True, slots=True)
class SchemaVerification:
    revision: str
    tables: int


class OwnerSchemaInspection(Protocol):
    def revision(self) -> str | None: ...
    def comparisons(self) -> Iterable[SchemaComparison]: ...
    def table_count(self) -> int: ...


class VerifyOwnerSchema:
    def __init__(self, source: OwnerSchemaInspection, reviewed_revision: str) -> None:
        self.source = source
        self.reviewed_revision = reviewed_revision

    def execute(self) -> SchemaVerification:
        if self.source.revision() != self.reviewed_revision:
            raise OwnerSchemaRejected("owner revision mismatch")
        for comparison in self.source.comparisons():
            comparison.reviewed.require_matches(comparison.observed)
        return SchemaVerification(self.reviewed_revision, self.source.table_count())
