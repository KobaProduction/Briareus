"""Reviewed owner schema contracts independent of SQLAlchemy and PostgreSQL clients."""

from dataclasses import dataclass

from common.domain.schema_predicates import (
    UnsupportedSchemaExpression,
    normalize_expression,
    schema_predicate,
)


class OwnerSchemaRejected(RuntimeError):
    """Unavailable or unverified authoritative schema; deny protected access."""


@dataclass(frozen=True, slots=True)
class ColumnShape:
    name: str
    nullable: bool
    type_name: str
    default: str = ""


@dataclass(frozen=True, slots=True)
class UniqueShape:
    columns: tuple[str, ...]
    name: str | None


@dataclass(frozen=True, slots=True)
class ForeignKeyShape:
    columns: tuple[str, ...]
    referred_schema: str | None
    referred_table: str
    referred_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IndexShape:
    name: str | None
    columns: tuple[str | None, ...]
    unique: bool
    predicate: str | None

    def require_matches(self, observed: "IndexShape") -> None:
        if self.columns != observed.columns or self.unique != observed.unique:
            raise OwnerSchemaRejected("owner index columns/uniqueness differ")
        if (self.predicate is None) != (observed.predicate is None):
            raise OwnerSchemaRejected("owner partial-index predicate absent or unexpected")
        if self.predicate is not None and observed.predicate is not None:
            self.require_predicate(observed.predicate)

    def require_predicate(self, observed: str) -> None:
        if self.predicate is None:
            raise OwnerSchemaRejected("owner partial-index predicate absent or unexpected")
        try:
            matches = schema_predicate(self.predicate) == schema_predicate(observed)
        except UnsupportedSchemaExpression as exc:
            raise OwnerSchemaRejected("owner partial-index predicate differs") from exc
        if not matches:
            raise OwnerSchemaRejected("owner partial-index predicate differs")


def require_sensitive_default(table: str, column: ColumnShape) -> None:
    if (
        table == "identity.users"
        and column.name == "browser_telemetry_opt_in"
        and column.default.lower().strip() not in {"false", "false::boolean", "'false'::boolean"}
    ):
        raise OwnerSchemaRejected("Identity browser telemetry default must deny")
    if (
        table == "projects.projects"
        and column.name == "lifecycle_status"
        and not active_default(column.default)
    ):
        raise OwnerSchemaRejected("Project lifecycle default must remain active")


def active_default(value: str) -> bool:
    try:
        return normalize_expression(value) == "'active'"
    except UnsupportedSchemaExpression:
        return False


@dataclass(frozen=True, slots=True)
class TableSchema:
    fullname: str
    column_names: frozenset[str]
    columns: tuple[ColumnShape, ...]
    primary_key: tuple[str, ...]
    checks: frozenset[str | None]
    uniques: tuple[UniqueShape, ...]
    indexes: tuple[IndexShape, ...]
    foreign_keys: frozenset[ForeignKeyShape]

    def require_columns(self, observed: "TableSchema") -> None:
        if self.column_names != observed.column_names:
            raise OwnerSchemaRejected("owner column inventory mismatch")
        by_name = {column.name: column for column in observed.columns}
        for expected in self.columns:
            actual = by_name[expected.name]
            if expected.nullable != actual.nullable:
                raise OwnerSchemaRejected("owner column nullability differs from reviewed metadata")
            if expected.type_name != actual.type_name:
                raise OwnerSchemaRejected("owner column type differs from reviewed metadata")
            require_sensitive_default(self.fullname, actual)

    def require_uniques(self, observed: "TableSchema") -> None:
        by_columns = {constraint.columns: constraint.name for constraint in observed.uniques}
        if (
            len(by_columns) != len(observed.uniques)
            or len(self.uniques) != len(observed.uniques)
            or {constraint.columns for constraint in self.uniques} != set(by_columns)
            or any(
                constraint.name is not None and by_columns[constraint.columns] != constraint.name
                for constraint in self.uniques
            )
        ):
            raise OwnerSchemaRejected("owner UNIQUE contract differs from reviewed head")

    def require_indexes(self, observed: "TableSchema") -> None:
        indexes = {index.name: index for index in observed.indexes}
        if not {index.name for index in self.indexes} <= indexes.keys():
            raise OwnerSchemaRejected("owner index inventory mismatch")
        for index in self.indexes:
            index.require_matches(indexes[index.name])

    def require_matches(self, observed: "TableSchema") -> None:
        self.require_columns(observed)
        if self.primary_key != observed.primary_key:
            raise OwnerSchemaRejected("owner primary-key contract changed")
        if not self.checks <= observed.checks:
            raise OwnerSchemaRejected("owner CHECK constraints missing")
        self.require_uniques(observed)
        self.require_indexes(observed)
        if self.foreign_keys != observed.foreign_keys:
            raise OwnerSchemaRejected("owner foreign-key verification failed")
