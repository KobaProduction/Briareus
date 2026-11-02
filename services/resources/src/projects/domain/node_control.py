"""Canonical enrolled control origin; no implicit network destination is allowed."""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class NodeOrigin:
    value: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", parsed.hostname)
            or parsed.port not in {None, 443}
        ):
            raise ValueError("Canonical HTTPS node origin required")
        object.__setattr__(self, "value", "https://" + parsed.hostname)
