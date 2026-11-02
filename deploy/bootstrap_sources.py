"""Read local plan inputs, never environment credentials or remote state."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from bootstrap_plan import ApplicationPlan, LocalBootstrapPlan, SharedBinding

REQUIRED = re.compile(r"\$\{([A-Z][A-Z0-9_]*):\?\}")
INTERPOLATED = re.compile(r"\$\{([A-Z][A-Z0-9_]*)(?::-[^}]*)?(?::\?)?\}")
SHARED_REF = re.compile(r"\{\{(team|project|environment)\.([A-Z][A-Z0-9_]*)\}\}\Z")


@dataclass(frozen=True)
class SourceRecord:
    fields: tuple[tuple[str, object], ...]

    @classmethod
    def parse(cls, value: object) -> SourceRecord:
        if not isinstance(value, Mapping):
            raise ValueError("invalid local bootstrap source object")
        pairs: list[tuple[str, object]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("invalid local bootstrap source property")
            pairs.append((key, item))
        return cls(tuple(pairs))

    def value(self, name: str, default: object = None) -> object:
        return next((value for key, value in self.fields if key == name), default)

    def string(self, name: str) -> str:
        value = self.value(name)
        if not isinstance(value, str):
            raise ValueError("missing local bootstrap source string")
        return value

    def items(self, name: str) -> tuple[object, ...]:
        value = self.value(name)
        if not isinstance(value, list):
            raise ValueError("missing local bootstrap source list")
        return tuple(value)


@dataclass(frozen=True)
class SharedNames:
    team: frozenset[str]
    project: frozenset[str]
    environment: frozenset[str]

    def permits(self, scope: str, name: str) -> bool:
        return name in {
            "team": self.team,
            "project": self.project,
            "environment": self.environment,
        }.get(scope, frozenset())


def _names(config: SourceRecord, key: str) -> frozenset[str]:
    values: list[str] = []
    for value in config.items(key):
        if not isinstance(value, str):
            raise ValueError("invalid local Shared variable name")
        values.append(value)
    return frozenset(values)


def _binding(
    key: str, value: object, allowed: SharedNames, declared: frozenset[str]
) -> SharedBinding:
    match = SHARED_REF.fullmatch(value) if isinstance(value, str) else None
    if match is None or key != match.group(2) or not allowed.permits(match.group(1), key):
        raise ValueError("unapproved local Shared variable binding")
    if key not in declared:
        raise ValueError("Shared variable is not a Compose interpolation input")
    return SharedBinding(key, match.group(1))


def _application(root: Path, value: object, allowed: SharedNames) -> ApplicationPlan:
    record = SourceRecord.parse(value)
    module = record.string("module")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", module):
        raise ValueError("invalid local Compose module path")
    path = (
        root.parent / "services/external" if module == "external" else root / module
    ) / "docker-compose.coolify.yaml"
    source = path.read_text()
    declared = frozenset(INTERPOLATED.findall(source))
    bindings = SourceRecord.parse(record.value("shared_variables", {}))
    return ApplicationPlan(
        record.string("name"),
        module,
        record.string("base_directory"),
        tuple(sorted(set(REQUIRED.findall(source)))),
        tuple(_binding(key, value, allowed, declared) for key, value in bindings.fields),
    )


def read_local_plan(root: Path, branch: str) -> LocalBootstrapPlan:
    value: object = json.loads((root / "APPLICATIONS.json").read_text())
    registry = SourceRecord.parse(value)
    if (registry.value("repository"), registry.value("server"), registry.value("environment")) != (
        "KobaProduction/briareus",
        "tambov",
        "development",
    ):
        raise ValueError("APPLICATIONS.json does not describe canonical Briareus DEV target")
    config = SourceRecord.parse(registry.value("configuration_contract"))
    if config.value("read_secret_values") is not False:
        raise ValueError("secret read policy must remain disabled")
    allowed = SharedNames(
        _names(config, "team_shared"),
        _names(config, "project_shared"),
        _names(config, "environment_shared"),
    )
    return LocalBootstrapPlan(
        branch, tuple(_application(root, item, allowed) for item in registry.items("applications"))
    )
