"""Reject stale dependency locks in independently deployable Python services."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate_native_lock(service: dict[str, object]) -> bool:
    if service.get("runtime") != "native":
        return False
    directory = service.get("directory")
    if not isinstance(directory, str):
        raise ValueError("Native service directory must be a path")
    owner = (ROOT / directory).resolve()
    if not owner.is_relative_to(ROOT / "services"):
        raise ValueError("Native build ownership must remain under services")
    if not all((owner / name).is_file() for name in ("Cargo.toml", "Cargo.lock")):
        raise ValueError(f"Missing native manifest/lock: {owner.relative_to(ROOT)}")
    return True


def project_paths() -> tuple[Path, ...]:
    document = json.loads((ROOT / "deploy/services.json").read_text(encoding="utf-8"))
    paths: set[Path] = set()
    for service in document["services"]:
        if validate_native_lock(service):
            continue  # Cargo owns the native lock; never run uv on a Rust image.
        images = [service["dockerfile"]] if service.get("dockerfile") else []
        images.extend(image["dockerfile"] for image in service.get("source_images", []))
        for dockerfile in images:
            owner = (ROOT / dockerfile).resolve().parent
            if not owner.is_relative_to(ROOT / "services"):
                raise ValueError("Python build ownership must remain under services")
            if not all((owner / name).is_file() for name in ("pyproject.toml", "uv.lock")):
                raise ValueError(
                    f"Missing owned dependency manifest/lock: {owner.relative_to(ROOT)}"
                )
            paths.add(owner)
    return tuple(sorted(paths))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, help="Validate one catalog-owned project")
    arguments = parser.parse_args()
    paths = project_paths()
    if arguments.project:
        selected = (ROOT / arguments.project).resolve()
        if selected not in paths:
            raise ValueError("Selected project must belong to a catalog Python image")
        paths = (selected,)
    for owner in paths:
        subprocess.run(["uv", "lock", "--check", "--project", str(owner)], cwd=ROOT, check=True)
    print(f"Verified {len(paths)} service-owned dependency locks")


if __name__ == "__main__":
    main()
