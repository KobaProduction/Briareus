"""Refresh exact source COPY/watch closures from the actual V1 import graph."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"


def module_file(module: str) -> Path | None:
    path = SOURCE.joinpath(*module.split("."))
    if path.with_suffix(".py").is_file():
        return path.with_suffix(".py")
    init = path / "__init__.py"
    return init if init.is_file() else None


def imports(path: Path) -> tuple[Path, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = path.relative_to(SOURCE).parts[:-1]
    found: set[Path] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.ImportFrom):
            prefix = package[: len(package) - node.level + 1] if node.level else ()
            module = ".".join((*prefix, *([node.module] if node.module else [])))
            names = [module, *(module + "." + alias.name for alias in node.names)]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        for name in names:
            target = module_file(name)
            if target is not None:
                found.add(target)
    return tuple(sorted(found))


def source_closure(owner: Path) -> tuple[str, ...]:
    pending = [*owner.rglob("*.py"), SOURCE / "common/asgi.py"]
    result: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in result:
            continue
        result.add(path)
        pending.extend(imports(path))
        for parent in path.parents:
            if parent == SOURCE:
                break
            init = parent / "__init__.py"
            if init.is_file():
                pending.append(init)
    return tuple(sorted(path.relative_to(ROOT).as_posix() for path in result))


def update_image(path: Path, sources: tuple[str, ...]) -> None:
    existing = path.read_text(encoding="utf-8").splitlines()
    lines = [line for line in existing if not line.startswith("COPY src/")]
    insertion = next(index for index, line in enumerate(lines) if line.startswith("ENV ASGI_APP="))
    lines[insertion:insertion] = [f"COPY {source} /app/{source}" for source in sources]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    path = ROOT / "deploy/services.json"
    document: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("services"), list):
        raise ValueError("Invalid BRI service catalog")
    for service in document["services"]:
        if not isinstance(service, dict):
            raise ValueError("Invalid BRI service entry")
        dockerfile = service.get("dockerfile")
        if not isinstance(dockerfile, str):
            continue
        image_path = ROOT / dockerfile
        entry = next(
            line for line in image_path.read_text().splitlines() if line.startswith("ENV ASGI_APP=")
        )
        package = entry.removeprefix("ENV ASGI_APP=").split(":")[0].rsplit(".", 1)[0]
        sources = source_closure(SOURCE.joinpath(*package.split(".")))
        update_image(image_path, sources)
        compose = service.get("compose")
        if not isinstance(compose, str):
            raise ValueError("Invalid BRI Compose path")
        service["watch_paths"] = [
            *sources,
            dockerfile,
            compose,
            compose.replace("docker-compose.yaml", "docker-compose.coolify.yaml"),
            "Dockerfile",
            "pyproject.toml",
            "uv.lock",
        ]
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print("Refreshed exact source import closures, image COPY paths and watcher catalog.")


if __name__ == "__main__":
    main()
