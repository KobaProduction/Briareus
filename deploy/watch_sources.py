"""Read reviewed registry and native Compose watch inputs without executing them."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from watch_policy import ImpactError, WatchPattern, WatchPlan


@dataclass(frozen=True)
class WatchSource:
    deployment: Path
    repository: Path

    def modules(self) -> tuple[str, ...]:
        registry: object = json.loads((self.deployment / "APPLICATIONS.json").read_text())
        if not isinstance(registry, dict) or not isinstance(registry.get("applications"), list):
            raise ImpactError("missing Application registry")
        modules: list[str] = []
        for application in registry["applications"]:
            if not isinstance(application, dict) or not isinstance(application.get("module"), str):
                raise ImpactError("invalid Application registry module")
            module = application["module"]
            if not module or module in modules:
                raise ImpactError("empty or duplicate Application registry module")
            modules.append(module)
        return tuple(modules)

    def plan(self, module: str) -> WatchPlan:
        folder = (
            self.repository / "services" / module
            if module in {"external", "platform", "resources"}
            else self.deployment / module
        )
        return parse_watch_plan(module, (folder / "docker-compose.coolify.yaml").read_text())

    def plans(self) -> tuple[WatchPlan, ...]:
        return tuple(self.plan(module) for module in self.modules())

    def explicit_path(self, pattern: str) -> Path:
        if pattern.startswith("deploy/"):
            return self.deployment / pattern.removeprefix("deploy/")
        return self.repository / pattern


def parse_watch_plan(module: str, source: str) -> WatchPlan:
    header = "x-watch-path-coolify:\n"
    if not source.startswith(header):
        raise ImpactError(f"{module}: missing top-level watch source")
    paths: list[WatchPattern] = []
    for line in source[len(header) :].splitlines():
        if line.startswith("  - "):
            item: object = json.loads(line[4:])
            if not isinstance(item, str):
                raise ImpactError(f"{module}: unsafe watch path")
            paths.append(WatchPattern(item))
        elif paths:
            break
        elif line.strip():
            raise ImpactError(f"{module}: invalid watch YAML")
    return WatchPlan(module, tuple(paths))


def representative(source: WatchSource, pattern: WatchPattern) -> str | None:
    value = pattern.value
    if value.endswith("/**"):
        root = source.repository / value[:-3]
        if not root.is_dir():
            return None
        return next(
            (
                path.relative_to(source.repository).as_posix()
                for path in sorted(root.rglob("*"))
                if _representative_file(path)
            ),
            None,
        )
    if not any(character in value for character in "*?["):
        return value if source.explicit_path(value).is_file() else None
    return None


def _representative_file(path: Path) -> bool:
    return (
        path.is_file()
        and not path.name.endswith((".pyc", ".map"))
        and "__pycache__" not in path.parts
    )
