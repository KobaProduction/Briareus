"""Claims exported by the existing local OAuth adapter; no role or grant authority."""

from pydantic import BaseModel, ConfigDict


class OAuthAccessClaims(BaseModel):
    """Known claim projection after JWT verification; extension claims stay at that boundary."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    iss: str
    aud: str | list[str]
    sub: str
    client_id: str
    exp: int
    iat: int
    jti: str
    username: str = ""
    scope: str = ""
    session_id: str = ""
