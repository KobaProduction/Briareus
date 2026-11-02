"""Map lease domain denial to the existing private credential-use error."""

from collections.abc import Iterator
from contextlib import contextmanager

from authorization.domain.credential_leases import CredentialLeaseDenied
from common.platform_errors import AccessDenied


@contextmanager
def lease_errors() -> Iterator[None]:
    try:
        yield
    except CredentialLeaseDenied as exc:
        raise AccessDenied(str(exc)) from None
