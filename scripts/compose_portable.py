"""Restricted, deterministic native resolver for Briareus owned Compose templates.

Supports the exact extension contract we own: one repository-local service
reference, mapping overlays, and volumes. Unsupported semantics fail closed.
Docker Compose is the optional external conformance oracle, not a requirement.
"""

from __future__ import annotations

import copy
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast


class YamlCodec(Protocol):
    def safe_load(self, stream: str) -> object: ...


yaml = cast(YamlCodec, import_module("yaml"))

ROOT = Path(__file__).resolve().parents[1]


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Compose mapping must use string keys")
    return cast(dict[str, object], value)


def read(path: Path) -> dict[str, object]:
    source = path.resolve()
    if not source.is_relative_to(ROOT) or not source.is_file():
        raise ValueError("Compose model must be a repository-owned file")
    return mapping(yaml.safe_load(source.read_text(encoding="utf-8")))


def _volume(item: object) -> dict[str, object]:
    if isinstance(item, dict):
        return dict(sorted(mapping(copy.deepcopy(item)).items()))
    if not isinstance(item, str):
        raise ValueError("Unsupported Compose volume declaration")
    parts = item.split(":")
    if len(parts) != 2 or not parts[0] or not parts[1] or not parts[1].startswith("/"):
        raise ValueError("Unsupported shorthand Compose mount; use long volume syntax")
    return {"source": parts[0], "target": parts[1], "type": "volume", "volume": {}}


def _merge_service(base: dict[str, object], overrides: dict[str, object]) -> dict[str, object]:
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if key == "extends":
            continue
        if key == "volumes":
            if not isinstance(value, list):
                raise ValueError("Compose extended volumes must be a list")
            existing = result.get("volumes", [])
            if not isinstance(existing, list):
                raise ValueError("Compose base volumes must be a list")
            result[key] = [*_normalize_volumes(existing), *_normalize_volumes(value)]
        elif key == "environment":
            result[key] = {
                **dict(sorted(mapping(result.get(key, {})).items())),
                **dict(sorted(mapping(value).items())),
            }
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = {**mapping(result[key]), **mapping(value)}
        else:
            result[key] = copy.deepcopy(value)
    return _canonical_service(result)


def _normalize_volumes(volumes: list[object]) -> list[dict[str, object]]:
    return [_volume(value) for value in volumes]


def _canonical_service(service: dict[str, object]) -> dict[str, object]:
    result = copy.deepcopy(service)
    for key in ("build", "healthcheck"):
        if key in result:
            result[key] = dict(sorted(mapping(result[key]).items()))
    if "networks" in result:
        values = result["networks"]
        if isinstance(values, list) and all(isinstance(x, str) for x in values):
            result["networks"] = {str(value): None for value in values}
        elif not isinstance(values, dict):
            raise ValueError("Unsupported Compose network declaration")
    if "volumes" in result:
        values = result["volumes"]
        if not isinstance(values, list):
            raise ValueError("Compose volumes must be a list")
        result["volumes"] = _normalize_volumes(values)
    return dict(sorted(result.items()))


def _resolve_includes(path: Path, model: dict[str, object]) -> dict[str, object]:
    includes = model["include"]
    if not isinstance(includes, list) or not includes:
        raise ValueError("Compose include must declare at least one file")
    for include in includes:
        if not isinstance(include, dict) or not isinstance(include.get("path"), str):
            raise ValueError("Compose include requires one path per entry")
        read((path.parent / include["path"]).resolve())
    return model


def _resolve_service(path: Path, spec: dict[str, object]) -> dict[str, object]:
    extension = spec.get("extends")
    if not isinstance(extension, dict):
        return _canonical_service(spec)
    link = mapping(extension)
    if set(link) != {"file", "service"} or not isinstance(link["file"], str):
        raise ValueError("Compose extends must specify one local file and service")
    template_path = (path.parent / link["file"]).resolve()
    template = read(template_path)
    parent = mapping(template.get("services"))
    parent_name = link["service"]
    if not isinstance(parent_name, str):
        raise ValueError("Compose extends service must be a string")
    inherited = mapping(parent[parent_name])
    if "extends" in inherited:
        raise ValueError("Nested Compose extends are not supported by the portable resolver")
    return _merge_service(inherited, spec)


def resolve(path: Path) -> dict[str, object]:
    model = read(path)
    if "services" not in model and "include" in model:
        return _resolve_includes(path, model)
    services = mapping(model.get("services"))
    if not services:
        raise ValueError("Compose must define at least one service")
    if not any("extends" in mapping(item) for item in services.values()):
        return model
    resolved = {name: _resolve_service(path, mapping(raw)) for name, raw in services.items()}
    model["services"] = dict(sorted(resolved.items()))
    if "volumes" in model:
        model["volumes"] = dict(sorted(mapping(model["volumes"]).items()))
    return dict(sorted(model.items()))
