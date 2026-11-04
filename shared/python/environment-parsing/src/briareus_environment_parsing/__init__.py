from __future__ import annotations


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def parse_csv_tuple(value: object) -> object:
    return _csv(value) if isinstance(value, str) else value


def parse_csv_frozenset(value: object) -> object:
    if isinstance(value, str):
        return frozenset(item.casefold() for item in _csv(value))
    if isinstance(value, (set, frozenset, tuple, list)):
        return frozenset(str(item).casefold() for item in value)
    return value
