"""Explicit credential-free native browser process environment."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BrowserProcessEnvironment:
    values: dict[str, str]
