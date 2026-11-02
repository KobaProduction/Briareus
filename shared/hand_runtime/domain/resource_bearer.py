"""Resource-bearer purpose constraints; no signature or Project authority is granted here."""

from dataclasses import dataclass

MAX_RESOURCE_TOKEN_SECONDS = 86_400


@dataclass(frozen=True, slots=True)
class ResourceBearer:
    subject: str
    client_id: str
    token_id: str
    audiences: tuple[str, ...]
    issued_at: int
    not_before: int
    expires_at: int

    def __post_init__(self) -> None:
        if not 1 <= len(self.subject) <= 256 or not self.subject.strip():
            raise ValueError("Invalid resource subject")
        self._require_client()
        self._require_token_id()
        self._require_audiences()

    def _require_client(self) -> None:
        if (
            not 1 <= len(self.client_id) <= 2048
            or not self.client_id.isascii()
            or any(character.isspace() for character in self.client_id)
        ):
            raise ValueError("Invalid resource client")

    def _require_token_id(self) -> None:
        if (
            not 1 <= len(self.token_id) <= 128
            or not self.token_id.isascii()
            or any(not 32 < ord(character) < 127 for character in self.token_id)
        ):
            raise ValueError("Invalid resource token identifier")

    def _require_audiences(self) -> None:
        if (
            not 1 <= len(self.audiences) <= 16
            or any(not audience for audience in self.audiences)
            or len(set(self.audiences)) != len(self.audiences)
        ):
            raise ValueError("Invalid resource audiences")

    def require_current(self, now: float) -> None:
        if not (
            self.expires_at > now
            and 0 < self.expires_at - self.issued_at <= MAX_RESOURCE_TOKEN_SECONDS
            and self.issued_at <= now
            and self.not_before <= now
            and self.not_before < self.expires_at
        ):
            raise ValueError("Resource token is outside its allowed lifetime")
