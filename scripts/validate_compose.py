"""Validate deployment models without credentials, interpolation, or runtime effects."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compose_paths() -> tuple[Path, ...]:
    document: object = json.loads((ROOT / "deploy/services.json").read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("services"), list):
        raise ValueError("Invalid BRI service catalog")
    paths = [ROOT / "docker-compose.yaml"]
    for entry in document["services"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("compose"), str):
            raise ValueError("Invalid BRI Compose catalog entry")
        path = (ROOT / entry["compose"]).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError("BRI Compose path must identify a repository file")
        paths.append(path)
        coolify = path.with_name("docker-compose.coolify.yaml")
        if coolify.is_file():
            paths.append(coolify)
    return tuple(dict.fromkeys(paths))


def main() -> None:
    paths = compose_paths()
    for path in paths:
        subprocess.run(
            [
                "docker", "compose", "--file", str(path), "config",
                "--no-interpolate", "--no-env-resolution", "--no-path-resolution", "--quiet",
            ],
            cwd=ROOT,
            check=True,
        )
    print(f"Validated {len(paths)} Compose entrypoints without runtime credentials")


if __name__ == "__main__":
    main()
