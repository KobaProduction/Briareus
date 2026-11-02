"""One-use preparation and bounded envelopes for provider-owned password changes."""

import re
from dataclasses import dataclass, field

from control_panel_api.domain.native_login import SecretText


class PasswordSetupUnavailable(Exception):
    """The provider or private preparation store could not confirm an outcome."""


class PasswordSetupDenied(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass(frozen=True, slots=True)
class PasswordPreparation:
    user_id: str
    code: SecretText = field(repr=False)
    csrf: SecretText = field(repr=False)
    cookie: SecretText = field(repr=False)
    expires_at: float

    def matches(self, user_id: str, code: SecretText) -> bool:
        return self.user_id == user_id and self.code.get_secret_value() == code.get_secret_value()

    def remaining(self, now: float) -> int:
        return int(self.expires_at - now)


def require_setup_code(code: SecretText) -> None:
    if re.fullmatch(r"[A-Za-z0-9]{64}", code.get_secret_value(), re.ASCII) is None:
        raise ValueError("Invalid password setup code")


def require_password_envelope(password: SecretText) -> None:
    # Password policy and credential validation remain exclusively with Rauthy.
    if not 1 <= len(password.get_secret_value()) <= 256:
        raise ValueError("Invalid password setup envelope")


def require_recovery_envelope(email: str, pow_solution: SecretText) -> None:
    if (
        not 3 <= len(email) <= 254
        or email.count("@") != 1
        or any(ord(character) < 33 for character in email)
    ):
        raise ValueError("Invalid recovery envelope")
    if len(pow_solution.get_secret_value()) > 256:
        raise ValueError("Invalid recovery envelope")
