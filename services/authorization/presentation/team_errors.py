"""Preserve existing Authorization HTTP errors at the Teams owner boundary."""

from collections.abc import Iterator
from contextlib import contextmanager

from common.platform_errors import AccessDenied, Conflict, InvalidInput, ResourceMissing
from teams.domain import TeamAccessDenied, TeamConflict, TeamInvalidInput, TeamResourceMissing


@contextmanager
def team_errors() -> Iterator[None]:
    try:
        yield
    except TeamAccessDenied as exc:
        raise AccessDenied(str(exc)) from exc
    except TeamConflict as exc:
        raise Conflict(str(exc)) from exc
    except TeamResourceMissing as exc:
        raise ResourceMissing(str(exc)) from exc
    except TeamInvalidInput as exc:
        raise InvalidInput(str(exc)) from exc
