"""Authority timestamps must retain timezone information at runtime boundaries."""

from datetime import datetime
from typing import TypeGuard


def aware_timestamp(value: object) -> TypeGuard[datetime]:
    return isinstance(value, datetime) and value.tzinfo is not None
