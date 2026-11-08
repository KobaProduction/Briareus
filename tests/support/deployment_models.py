"""Static contract model for the single approved MCP baseline, independent of Docker CLI.

The host renderer and its acceptance contracts use Docker Compose to validate real
merge semantics. Offline backend contracts inspect the baseline's declared fields.
"""

import copy
from dataclasses import dataclass
from pathlib import Path

from scripts.briareus_coolify import ROOT, mapping
from scripts.briareus_coolify import load_model as raw_model


def generic_model(path: Path) -> dict[str, object]:
    model = raw_model(path)
    for name, value in mapping(model["services"]).items():
        service = mapping(value)
        if "extends" not in service:
            continue
        reference = mapping(service["extends"])
        template = (path.parent / str(reference["file"])).resolve()
        if template != ROOT / "deploy/templates/mcp-service.yaml":
            raise ValueError("Internal MCP owners must use the common deployment template")
        baseline = copy.deepcopy(mapping(mapping(raw_model(template)["services"])["mcp-service"]))
        environment = {
            **mapping(baseline["environment"]),
            **mapping(service.get("environment", {})),
        }
        baseline.update({key: value for key, value in service.items() if key != "extends"})
        baseline["environment"] = environment
        mapping(model["services"])[name] = baseline
    return model


@dataclass(frozen=True)
class Mount:
    source: str
    target: str
    mount_type: str = "volume"
    read_only: bool = False


def service_mounts(service: dict[str, object]) -> tuple[Mount, ...]:
    values = service.get("volumes", [])
    if not isinstance(values, list):
        raise ValueError("Service mounts must be a list")
    result = []
    for value in values:
        if isinstance(value, str):
            source, separator, target = value.partition(":")
            if not separator:
                raise ValueError("Named deployment mounts require an explicit target")
            result.append(Mount(source, target))
        else:
            mount = mapping(value)
            result.append(
                Mount(
                    str(mount["source"]),
                    str(mount["target"]),
                    str(mount.get("type", "volume")),
                    bool(mount.get("read_only", False)),
                )
            )
    return tuple(result)
