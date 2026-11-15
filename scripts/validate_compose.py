"""Validate deployment models without credentials, interpolation, or runtime effects."""

from __future__ import annotations

import argparse
import json
import subprocess
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compose_paths() -> tuple[Path, ...]:
    document: object = json.loads((ROOT / "deploy/services.json").read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("services"), list):
        raise ValueError("Invalid Briareus service catalog")
    paths = [ROOT / "docker-compose.yaml"]
    for entry in document["services"]:
        path = _catalog_compose_path(entry, fixture=False)
        paths.append(path)
        coolify = path.with_name("docker-compose.coolify.yaml")
        if coolify.is_file():
            paths.append(coolify)
    fixtures = document.get("fixtures", [])
    if not isinstance(fixtures, list):
        raise ValueError("Invalid Briareus fixture catalog")
    for entry in fixtures:
        path = _catalog_compose_path(entry, fixture=True)
        paths.append(path)
    return tuple(dict.fromkeys(paths))


def _catalog_compose_path(entry: object, *, fixture: bool) -> Path:
    relative = entry.get("compose") if isinstance(entry, dict) else None
    if not isinstance(relative, str):
        message = "fixture path" if fixture else "Compose catalog entry"
        raise ValueError(f"Invalid Briareus {message}")
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        kind = "fixture" if fixture else "Compose"
        raise ValueError(f"Briareus {kind} path must identify a repository file")
    return path


def _validate_with_docker(paths: tuple[Path, ...]) -> None:
    for path in paths:
        subprocess.run(
            [
                "docker",
                "compose",
                "--file",
                str(path),
                "config",
                "--no-interpolate",
                "--no-env-resolution",
                "--no-path-resolution",
                "--quiet",
            ],
            cwd=ROOT,
            check=True,
        )
    print(f"Docker Compose validated {len(paths)} entrypoints")


def _validate_portable(paths: tuple[Path, ...]) -> None:
    module = "scripts.compose_portable" if __package__ else "compose_portable"
    resolver = import_module(module).resolve
    for path in paths:
        model = resolver(path)
        if not (isinstance(model.get("services"), dict) and model["services"]) and not (
            isinstance(model.get("include"), list) and model["include"]
        ):
            raise ValueError(f"Compose services/includes missing: {path}")
    print(f"Portable parser validated {len(paths)} Compose entrypoints (Docker not required)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docker", action="store_true", help="Use Docker Compose as an optional conformance check"
    )
    options = parser.parse_args()
    paths = compose_paths()
    if options.docker:
        _validate_with_docker(paths)
    else:
        _validate_portable(paths)


if __name__ == "__main__":
    main()
