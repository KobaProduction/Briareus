"""Bounded Git policy names shared by management and execution configuration."""


def checked_policy_names(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) > 64 or any(
        not item.strip() or len(item) > 128 or any(ord(c) < 32 for c in item) for item in values
    ):
        raise ValueError("Bounded non-empty policy entries required")
    return tuple(dict.fromkeys(item.strip() for item in values))
