"""Refresh exact image inputs and owner-scoped Briareus deployment watches."""

from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
EXPORT = ROOT / "deploy/watch-paths.txt"
BASE_INPUTS = (
    "Dockerfile", ".dockerignore", "pyproject.toml", "uv.lock", "scripts/bri_dockerfiles.py"
)


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


def string_list(record: Mapping[str, object], key: str) -> tuple[str, ...]:
    values = record.get(key, [])
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError(f"Invalid Briareus catalog {key}")
    return tuple(values)


def source_owners(service: Mapping[str, object]) -> tuple[str, ...]:
    owners = string_list(service, "source_owners")
    for owner in owners:
        path = (ROOT / owner).resolve()
        if (
            not path.is_relative_to(ROOT)
            or not path.is_dir()
            or path in {ROOT, SOURCE, SOURCE / "common"}
            or "*" in owner
        ):
            raise ValueError("Briareus source owners must be specific repository directories")
    return owners


def package_resources(service: Mapping[str, object]) -> tuple[str, ...]:
    resources = string_list(service, "package_resources")
    for resource in resources:
        path = (ROOT / resource).resolve()
        if not path.is_relative_to(SOURCE) or not path.is_file():
            raise ValueError("Briareus package resources must identify source files")
    return resources


def owned_sources(owners: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({
        source
        for owner in owners
        if (ROOT / owner).is_relative_to(SOURCE)
        for source in source_closure(ROOT / owner)
    }))


def source_images(service: Mapping[str, object]) -> tuple[tuple[Path, tuple[str, ...]], ...]:
    result: list[tuple[Path, tuple[str, ...]]] = []
    images = service.get("source_images", [])
    if not isinstance(images, list):
        raise ValueError("Invalid Briareus source images")
    for image in images:
        if not isinstance(image, dict):
            raise ValueError("Invalid Briareus source image")
        owner, dockerfile = image.get("source_owner"), image.get("dockerfile")
        if not isinstance(owner, str) or not isinstance(dockerfile, str):
            raise ValueError("Invalid Briareus source image ownership")
        result.append((ROOT / dockerfile, source_closure(SOURCE / owner)))
    dockerfile = service.get("dockerfile")
    if isinstance(dockerfile, str):
        sources = owned_sources(source_owners(service))
        result.append((ROOT / dockerfile, (*sources, *package_resources(service))))
    return tuple(result)


def image_text(path: Path, sources: tuple[str, ...]) -> str:
    lines = [
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.startswith("COPY src/")
    ]
    insertion = next(index for index, line in enumerate(lines) if line.startswith("ENV ASGI_APP="))
    lines[insertion:insertion] = [f"COPY {source} /app/{source}" for source in sources]
    return "\n".join(lines) + "\n"


def compose_path(service: Mapping[str, object]) -> str:
    value = service.get("compose")
    if not isinstance(value, str) or not (ROOT / value).is_file():
        raise ValueError("Invalid Briareus Compose path")
    return value


def watch_paths(service: Mapping[str, object]) -> tuple[str, ...]:
    owners = source_owners(service)
    shared = (
        source for source in owned_sources(owners)
        if not any(source.startswith(owner + "/") for owner in owners)
    )
    paths = [
        str(Path(compose_path(service)).parent.as_posix()) + "/**",
        *(owner + "/**" for owner in owners),
        *shared,
        *(BASE_INPUTS if source_images(service) else ()),
        *string_list(service, "extra_watch_paths"),
    ]
    return tuple(dict.fromkeys(paths))


def services(document: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    values = document.get("services")
    if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
        raise ValueError("Invalid Briareus service catalog")
    return tuple(values)


def export_text(document: Mapping[str, object]) -> str:
    lines = [
        "Briareus V1 — Coolify deployment inputs",
        "Generated by scripts/bri_catalog.py. Paths are repository-relative.",
        "Copy only the lines below Watch Paths into the named resource.",
        "Create NEW resources; do not modify Legacy MCP Bridge or V2 resources.",
    ]
    for service in services(document):
        compose = Path(compose_path(service))
        lines.extend([
            "", f"[{service['name']}]", "Branch: v1",
            f"Base Directory: /{compose.parent.as_posix()}",
            "Compose Location: /docker-compose.coolify.yaml", "Watch Paths:",
            *string_list(service, "watch_paths"),
        ])
    return "\n".join(lines) + "\n"


def refresh(document: dict[str, object], *, check: bool, images: bool) -> None:
    stale: list[str] = []
    for service in services(document):
        expected = list(watch_paths(service))
        if check and service.get("watch_paths") != expected:
            stale.append(f"watch paths: {service.get('name')}")
        service["watch_paths"] = expected
        if images:
            for path, sources in source_images(service):
                expected_image = image_text(path, sources)
                if check:
                    if path.read_text(encoding="utf-8") != expected_image:
                        stale.append(path.relative_to(ROOT).as_posix())
                else:
                    path.write_text(expected_image, encoding="utf-8")
    if stale:
        raise ValueError("Regenerate Briareus deployment inputs: " + ", ".join(stale))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail on stale COPY/watch/export inputs"
    )
    parser.add_argument(
        "--watch-only", action="store_true", help="Do not read or rewrite COPY blocks"
    )
    arguments = parser.parse_args()
    path = ROOT / "deploy/services.json"
    document: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Invalid Briareus service catalog")
    refresh(document, check=arguments.check, images=not arguments.watch_only)
    exported = export_text(document)
    if arguments.check:
        if not EXPORT.is_file() or EXPORT.read_text(encoding="utf-8") != exported:
            raise ValueError("Regenerate deploy/watch-paths.txt")
    else:
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        EXPORT.write_text(exported, encoding="utf-8")
    print(
        "Verified Briareus deployment inputs." if arguments.check
        else "Refreshed Briareus COPY/watch inputs."
    )


if __name__ == "__main__":
    main()
