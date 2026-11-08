"""Read the current container's cgroup limits without accessing the Docker daemon."""
from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from briareus_json_values import JsonObject, StrictModel, json_object


class ContainerResources(StrictModel):
    available: bool
    cpu_cores: float | None = None
    memory_bytes: int | None = None
    pids_limit: int | None = None
    pids_current: int | None = None
    zombie_processes: int = 0


def _number(path: Path) -> int | None:
    try:
        value = path.read_text().strip()
        return int(value) if value != "max" else None
    except (OSError, ValueError):
        return None


def container_resources(root: Path = Path("/sys/fs/cgroup")) -> JsonObject:
    cpu: float | None = None
    try:
        quota, period = (root / "cpu.max").read_text().split()
        if quota != "max":
            cpu = int(quota) / int(period)
    except (OSError, ValueError, ZeroDivisionError):
        pass
    zombies = 0
    for process in Path("/proc").glob("[0-9]*/stat"):
        with suppress(OSError, IndexError):
            zombies += process.read_text().rsplit(")", 1)[1].split()[0] == "Z"
    return json_object(ContainerResources(
        available=(root / "cpu.max").exists(), cpu_cores=cpu,
        memory_bytes=_number(root / "memory.max"),
        pids_limit=_number(root / "pids.max"), pids_current=_number(root / "pids.current"),
        zombie_processes=zombies,
    ).model_dump(mode="json"))
