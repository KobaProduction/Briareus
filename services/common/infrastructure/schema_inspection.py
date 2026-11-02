"""Reflect one owner's SQL metadata into framework-free schema observations."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sqlalchemy import MetaData, Table, UniqueConstraint
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.engine.reflection import Inspector

from common.application.schema_verification import SchemaComparison
from common.domain.schema_contracts import (
    ColumnShape,
    ForeignKeyShape,
    IndexShape,
    OwnerSchemaRejected,
    TableSchema,
    UniqueShape,
)


def schema_name(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise OwnerSchemaRejected("unsupported reviewed schema object name")


def reviewed_columns(table: Table, pg: Dialect) -> tuple[ColumnShape, ...]:
    return tuple(
        ColumnShape(
            column.name, bool(column.nullable), str(column.type.compile(dialect=pg)).upper()
        )
        for column in table.columns
    )


def reviewed_indexes(table: Table) -> tuple[IndexShape, ...]:
    result: list[IndexShape] = []
    for index in table.indexes:
        predicate: object = index.dialect_options["postgresql"].get("where")
        result.append(
            IndexShape(
                schema_name(index.name),
                tuple(column.name for column in index.columns),
                bool(index.unique),
                str(predicate) if predicate is not None else None,
            )
        )
    return tuple(result)


def reviewed_schema(table: Table, pg: Dialect) -> TableSchema:
    return TableSchema(
        table.fullname,
        frozenset(column.name for column in table.columns),
        reviewed_columns(table, pg),
        tuple(column.name for column in table.primary_key.columns),
        frozenset(
            schema_name(constraint.name)
            for constraint in table.constraints
            if constraint.__class__.__name__ == "CheckConstraint" and constraint.name
        ),
        tuple(
            UniqueShape(
                tuple(column.name for column in constraint.columns), schema_name(constraint.name)
            )
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        ),
        reviewed_indexes(table),
        frozenset(
            ForeignKeyShape(
                tuple(foreign.column_keys),
                foreign.referred_table.schema,
                foreign.referred_table.name,
                tuple(element.column.name for element in foreign.elements),
            )
            for foreign in table.foreign_key_constraints
        ),
    )


def observed_columns(inspector: Inspector, table: Table) -> tuple[ColumnShape, ...]:
    pg = inspector.bind.dialect
    return tuple(
        ColumnShape(
            column["name"],
            bool(column["nullable"]),
            str(column["type"].compile(dialect=pg)).upper(),
            str(column.get("default") or ""),
        )
        for column in inspector.get_columns(table.name, schema=table.schema)
    )


def observed_indexes(inspector: Inspector, table: Table) -> tuple[IndexShape, ...]:
    result: list[IndexShape] = []
    for index in inspector.get_indexes(table.name, schema=table.schema):
        predicate: object = index.get("dialect_options", {}).get("postgresql_where")
        result.append(
            IndexShape(
                schema_name(index["name"]),
                tuple(index.get("column_names") or ()),
                bool(index.get("unique")),
                str(predicate) if predicate is not None else None,
            )
        )
    return tuple(result)


def observed_schema(inspector: Inspector, table: Table) -> TableSchema:
    names = frozenset(
        column["name"] for column in inspector.get_columns(table.name, schema=table.schema)
    )
    return TableSchema(
        table.fullname,
        names,
        observed_columns(inspector, table),
        tuple(
            inspector.get_pk_constraint(table.name, schema=table.schema).get("constrained_columns")
            or ()
        ),
        frozenset(
            schema_name(constraint["name"])
            for constraint in inspector.get_check_constraints(table.name, schema=table.schema)
        ),
        tuple(
            UniqueShape(
                tuple(constraint.get("column_names") or ()), schema_name(constraint.get("name"))
            )
            for constraint in inspector.get_unique_constraints(table.name, schema=table.schema)
        ),
        observed_indexes(inspector, table),
        frozenset(
            ForeignKeyShape(
                tuple(foreign["constrained_columns"]),
                foreign["referred_schema"],
                foreign["referred_table"],
                tuple(foreign["referred_columns"]),
            )
            for foreign in inspector.get_foreign_keys(table.name, schema=table.schema)
        ),
    )


@dataclass(frozen=True, slots=True)
class SqlOwnerSchemaInspection:
    metadata: MetaData
    inspector: Inspector
    read_revision: Callable[[], str | None]

    def revision(self) -> str | None:
        return self.read_revision()

    def comparisons(self) -> Iterable[SchemaComparison]:
        for table in self.metadata.sorted_tables:
            yield SchemaComparison(
                reviewed_schema(table, self.inspector.bind.dialect),
                observed_schema(self.inspector, table),
            )

    def table_count(self) -> int:
        return len(self.metadata.tables)
