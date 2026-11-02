"""Persisted local browser access flags and presentation preference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(slots=True)
class BrowserPolicy:
    agent_access_enabled: bool = True
    developer_access_enabled: bool = False
    color_scheme: Literal["system", "light", "dark"] = "dark"
