"""Decode purpose fields only after the SDK verified signature, issuer and audience.

The projection ignores unrelated provider claims and rejects proof binding and
actor delegation. It never confers Project/Cedar authority.
"""

import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, ValidationError

from .domain.resource_bearer import ResourceBearer


class ResourceBearerDocument(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    sub: StrictStr
    azp: StrictStr
    jti: StrictStr
    typ: Literal["Bearer"]
    aud: StrictStr | list[StrictStr]
    exp: StrictInt
    iat: StrictInt
    nbf: StrictInt
    cnf: None = None
    act: None = None

    def bearer(self) -> ResourceBearer:
        audiences = (self.aud,) if isinstance(self.aud, str) else tuple(self.aud)
        return ResourceBearer(self.sub, self.azp, self.jti, audiences, self.iat, self.nbf, self.exp)


def decode_verified_bearer(claims: object) -> ResourceBearer | None:
    """Raw SDK claims are consumed here and never become an application contract."""
    try:
        bearer = ResourceBearerDocument.model_validate(claims).bearer()
        bearer.require_current(time.time())
    except (ValidationError, ValueError):
        return None
    return bearer
