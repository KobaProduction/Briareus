"""Local bootstrap planning policies; no remote reconciliation authority."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SharedBinding:
    name: str
    scope: str

    @property
    def reference(self) -> str:
        return "{{" + self.scope + "." + self.name + "}}"


@dataclass(frozen=True)
class ApplicationPlan:
    name: str
    module: str
    base_directory: str
    required_inputs: tuple[str, ...]
    bindings: tuple[SharedBinding, ...]


@dataclass(frozen=True)
class LocalBootstrapPlan:
    branch: str
    applications: tuple[ApplicationPlan, ...]

    def __post_init__(self) -> None:
        if self.branch.startswith("TO_BE_") or not re.fullmatch(
            r"[A-Za-z0-9._/-]{1,160}", self.branch
        ):
            raise ValueError("invalid/unreviewed Git branch/ref")
        names = tuple(app.name for app in self.applications)
        modules = tuple(app.module for app in self.applications)
        if len(names) < 11 or len(set(names)) != len(names):
            raise ValueError("APPLICATIONS.json requires nonempty unique Application names")
        if len(set(modules)) != len(modules):
            raise ValueError("APPLICATIONS.json must have explicit unique module identities")
        required = {key for app in self.applications for key in app.required_inputs}
        classified = {binding.name for app in self.applications for binding in app.bindings}
        unknown = required - classified - {"OTEL_SERVICE_NAME", "RAUTHY_TRUSTED_PROXIES"}
        if unknown:
            raise ValueError(
                "unclassified required variables in Compose: " + ", ".join(sorted(unknown))
            )
