"""Preserve management error contracts at legacy and current owner boundaries."""

from collections.abc import Iterator
from contextlib import contextmanager

from authorization.domain.sessions import InvalidSessionInput, SessionAccessDenied, SessionConflict
from common.platform_errors import AccessDenied, Conflict, InvalidInput


@contextmanager
def session_errors() -> Iterator[None]:
    try:
        yield
    except SessionAccessDenied as exc:
        raise AccessDenied(str(exc)) from exc
    except SessionConflict as exc:
        raise Conflict(str(exc)) from exc
    except InvalidSessionInput as exc:
        raise InvalidInput(str(exc)) from exc
