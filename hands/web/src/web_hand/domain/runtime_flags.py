"""Trusted placement switches must be actual booleans."""


def require_boolean(value: object, message: str) -> None:
    if type(value) is not bool:
        raise ValueError(message)
