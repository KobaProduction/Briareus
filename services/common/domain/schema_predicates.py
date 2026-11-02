"""Finite parser for the reviewed owner index predicates, not general SQL equivalence."""

import re
from dataclasses import dataclass
from typing import Literal


class UnsupportedSchemaExpression(ValueError):
    """A reflected expression is outside the reviewed predicate vocabulary."""


_QUOTED = re.compile(r"('(?:''|[^'])*')")
_CAST = re.compile(r"::(?:character\s+varying|varchar|text)(?:\[\])?(?![a-z0-9_])")
_COLUMN = r"([a-z_][a-z_0-9]*)"
_NULL = re.compile(_COLUMN + r"\s+is\s+(not\s+)?null")
_IN = re.compile(_COLUMN + r"\s+(not\s+)?in\s+(.+)")
_ARRAY = re.compile(_COLUMN + r"\s*(=|<>)\s*(any|all)\s+array\s*\[(.*)\]")
_VALUES = re.compile(r"'(?:''|[^'])*'(?:\s*,\s*'(?:''|[^'])*')*")
_CALL = re.compile(r"([a-z_][a-z_0-9]*)\s*\(")


def normalize_expression(sql: str) -> str:
    parts = _QUOTED.split(sql)
    for offset in range(0, len(parts), 2):
        lowered = parts[offset].lower()
        if any(
            match.group(1) not in {"in", "any", "all", "and"} for match in _CALL.finditer(lowered)
        ):
            raise UnsupportedSchemaExpression("owner schema expressions cannot call functions")
        parts[offset] = _CAST.sub("", lowered).replace("(", "").replace(")", "")
    # Whitespace inside quoted literals is meaningful and must remain untouched.
    for offset in range(0, len(parts), 2):
        parts[offset] = re.sub(r"\s+", " ", parts[offset])
    return "".join(parts).strip()


@dataclass(frozen=True, slots=True)
class PredicateClause:
    column: str
    operation: Literal["is_null", "is_not_null", "in", "not_in"]
    values: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SchemaPredicate:
    clauses: tuple[PredicateClause, ...]


def membership_values(value: str) -> tuple[str, ...]:
    if _VALUES.fullmatch(value.strip()) is None:
        raise UnsupportedSchemaExpression("unsupported owner index membership values")
    return tuple(match.group() for match in _QUOTED.finditer(value))


def membership(sql: str) -> PredicateClause | None:
    direct = _IN.fullmatch(sql)
    if direct is not None:
        column, negated, values = direct.groups()
        return PredicateClause(column, "not_in" if negated else "in", membership_values(values))
    array = _ARRAY.fullmatch(sql)
    if array is None:
        return None
    column, operator, quantifier, values = array.groups()
    if (operator, quantifier) not in {("=", "any"), ("<>", "all")}:
        raise UnsupportedSchemaExpression("unsupported owner index membership operator")
    return PredicateClause(column, "in" if operator == "=" else "not_in", membership_values(values))


def schema_predicate(sql: str) -> SchemaPredicate:
    normalized = normalize_expression(sql)
    member = membership(normalized)
    if member is not None:
        return SchemaPredicate((member,))
    clauses: list[PredicateClause] = []
    for part in re.split(r"\s+and\s+", normalized):
        null = _NULL.fullmatch(part.strip())
        if null is None:
            raise UnsupportedSchemaExpression("unsupported owner index predicate")
        column, negated = null.groups()
        clauses.append(PredicateClause(column, "is_not_null" if negated else "is_null"))
    return SchemaPredicate(tuple(clauses))
