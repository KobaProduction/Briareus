"""HTTP adaptation of the retained session admission outcomes."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from domain.web_session import (
    WebAdministratorRequired,
    WebIdentityUnavailable,
    WebInvalidCredentials,
    WebUserDisabled,
)
from fastapi import HTTPException


@dataclass(frozen=True, slots=True)
class WebSessionResponse:
    authenticated: bool
    username: str | None


@contextmanager
def web_session_errors() -> Iterator[None]:
    try:
        yield
    except WebIdentityUnavailable as exc:
        raise HTTPException(503, "authorization identity service unavailable") from exc
    except WebInvalidCredentials as exc:
        raise HTTPException(401, "invalid credentials") from exc
    except WebAdministratorRequired as exc:
        raise HTTPException(403, "superuser required") from exc
    except WebUserDisabled as exc:
        raise HTTPException(403, "local user disabled") from exc
