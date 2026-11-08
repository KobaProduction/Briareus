"""Service ownership, package-level image inputs and private directory watch export."""

from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / ".local/briareus-v1-coolify/watch-paths.txt"
BEGIN = "# BEGIN BRIAREUS SOURCE PACKAGES"
END = "# END BRIAREUS SOURCE PACKAGES"


@lru_cache
def source_roots() -> tuple[Path, ...]:
    patterns = (
        "services/*/src",
        "services/control-panel/*/src",
        "services/hands/*/src",
        "services/hands/*/*/src",
        "services/dependencies/*/src",
        "shared/*/src",
        "shared/*/*/src",
        "shared/*/*/*/src",
    )
    return tuple(sorted({p for pattern in patterns for p in ROOT.glob(pattern)}))


@lru_cache
def packages() -> dict[str, Path]:
    result = {}
    for source in source_roots():
        for package in source.iterdir():
            if not package.is_dir() or not (package / "__init__.py").is_file():
                continue
            if package.name in result:
                raise ValueError(f"Duplicate source package: {package.name}")
            result[package.name] = package
    return result


def module_file(module: str) -> Path | None:
    head, _, tail = module.partition(".")
    package = packages().get(head)
    if package is None:
        return None
    path = package.joinpath(*tail.split(".")) if tail else package
    if path.with_suffix(".py").is_file():
        return path.with_suffix(".py")
    init = path / "__init__.py"
    return init if init.is_file() else None


@lru_cache
def imports(path: Path) -> tuple[Path, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    source = next(root for root in source_roots() if path.is_relative_to(root))
    package = path.relative_to(source).parts[:-1]
    found = set()
    for node in ast.walk(tree):
        for name in import_names(node, package, path):
            target = module_file(name)
            if target is not None:
                found.add(target)
    return tuple(sorted(found))


def require_resolved_import(name: str, path: Path) -> None:
    if name.partition(".")[0] in packages() and module_file(name) is None:
        raise ValueError(f"Unresolved first-party import in {path}: {name}")


def import_names(node: ast.AST, package: tuple[str, ...], path: Path) -> list[str]:
    if isinstance(node, ast.ImportFrom):
        prefix = package[: len(package) - node.level + 1] if node.level else ()
        module = ".".join((*prefix, *([node.module] if node.module else [])))
        require_resolved_import(module, path)
        return [module, *(module + "." + alias.name for alias in node.names)]
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
        for name in names:
            require_resolved_import(name, path)
        return names
    return []


def package_owner(path: Path) -> Path:
    return next(package for package in packages().values() if path.is_relative_to(package))


@lru_cache
def source_packages(owners: tuple[str, ...]) -> tuple[Path, ...]:
    pending = [ROOT / owner for owner in owners]
    runtime = packages().get("briareus_service_runtime")
    if pending and runtime is not None:
        pending.append(runtime)
    result = set()
    while pending:
        package = pending.pop()
        if package in result:
            continue
        if not (package / "__init__.py").is_file():
            raise ValueError(f"Invalid source package: {package.relative_to(ROOT)}")
        result.add(package)
        for path in package.rglob("*.py"):
            pending.extend(package_owner(target) for target in imports(path))
    return tuple(sorted(result))


def source_closure(owner: Path) -> tuple[str, ...]:
    return owned_sources((owner.relative_to(ROOT).as_posix(),))


def string_list(record: Mapping[str, object], key: str) -> tuple[str, ...]:
    values = record.get(key, [])
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError(f"Invalid Briareus catalog {key}")
    return tuple(values)


def source_owners(service: Mapping[str, object]) -> tuple[str, ...]:
    owners = string_list(service, "source_owners")
    for owner in owners:
        path = (ROOT / owner).resolve()
        if not path.is_relative_to(ROOT / "services") or not (path / "__init__.py").is_file():
            raise ValueError("Source owners must be service-owned Python packages")
    return owners


def owned_sources(owners: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(ROOT).as_posix()
            for package in source_packages(owners)
            for path in package.rglob("*.py")
        )
    )


def package_resources(service: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(ROOT).as_posix()
            for owner in source_owners(service)
            for path in (ROOT / owner).rglob("*")
            if path.is_file()
            and path.suffix not in {".py", ".pyc"}
            and "__pycache__" not in path.parts
        )
    )


def source_images(service: Mapping[str, object]) -> tuple[tuple[Path, tuple[str, ...]], ...]:
    result = []
    images = service.get("source_images", [])
    if not isinstance(images, list):
        raise ValueError("Invalid source image catalog")
    for image in images:
        if not isinstance(image, dict):
            raise ValueError("Invalid source image")
        owner, dockerfile = image.get("source_owner"), image.get("dockerfile")
        if not isinstance(owner, str) or not isinstance(dockerfile, str):
            raise ValueError("Invalid source image ownership")
        source = source_packages((owner,))
        result.append((ROOT / dockerfile, tuple(p.relative_to(ROOT).as_posix() for p in source)))
    dockerfile = service.get("dockerfile")
    if isinstance(dockerfile, str):
        source = source_packages(source_owners(service))
        result.append((ROOT / dockerfile, tuple(p.relative_to(ROOT).as_posix() for p in source)))
    return tuple(result)


def image_text(path: Path, sources: tuple[str, ...]) -> str:
    source = path.read_text(encoding="utf-8")
    block = "\n".join(
        [BEGIN, *(f"COPY {name} /app/src/{Path(name).name}" for name in sources), END]
    )
    if BEGIN in source:
        before, _, rest = source.partition(BEGIN)
        _, separator, after = rest.partition(END)
        if not separator:
            raise ValueError("Incomplete source package block")
        return before + block + after
    lines = [
        line for line in source.splitlines() if not (line.startswith("COPY ") and "/src/" in line)
    ]
    insertion = next(i for i, line in enumerate(lines) if line.startswith("ENV ASGI_APP="))
    lines[insertion:insertion] = block.splitlines()
    return "\n".join(lines) + "\n"


def compose_path(service: Mapping[str, object]) -> str:
    path = service.get("compose")
    if not isinstance(path, str) or not (ROOT / path).is_file():
        raise ValueError("Invalid Briareus Compose path")
    return path


def watch_paths(service: Mapping[str, object]) -> tuple[str, ...]:
    directory = Path(compose_path(service)).parent
    shared = set()
    for package in source_packages(source_owners(service)):
        relative = package.relative_to(ROOT)
        if relative.parts[0] == "shared":
            shared.add(package.parent.parent.relative_to(ROOT).as_posix() + "/**")
        elif not package.is_relative_to(ROOT / directory):
            raise ValueError(f"Cross-service source dependency: {service['name']} -> {relative}")
    if directory.is_relative_to(Path("services/hands")):
        shared.add("deploy/templates/**")
    return (directory.as_posix() + "/**", *sorted(shared))


def services(document: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    values = document.get("services")
    if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
        raise ValueError("Invalid Briareus service catalog")
    return tuple(values)


def export_text(document: Mapping[str, object]) -> str:
    lines = ["Briareus V1 — private Coolify setup handout", "Branch: v1"]
    for service in services(document):
        compose = Path(compose_path(service))
        lines.extend(
            [
                "",
                f"[{service['name']}]",
                f"Base Directory: /{compose.parent.as_posix()}",
                "Compose Location: /docker-compose.coolify.yaml",
                "Watch Paths:",
                *string_list(service, "watch_paths"),
            ]
        )
    return "\n".join(lines) + "\n"


def refresh(document: dict[str, object], *, check: bool, images: bool) -> None:
    source_roots.cache_clear()
    packages.cache_clear()
    imports.cache_clear()
    source_packages.cache_clear()
    stale = []
    for service in services(document):
        expected = list(watch_paths(service))
        if check and service.get("watch_paths") != expected:
            stale.append(f"watch paths: {service.get('name')}")
        service["watch_paths"] = expected
        if images:
            stale.extend(refresh_images(service, check=check))
    if stale:
        raise ValueError("Regenerate Briareus deployment inputs: " + ", ".join(stale))


def refresh_images(service: Mapping[str, object], *, check: bool) -> list[str]:
    stale = []
    for path, sources in source_images(service):
        expected = image_text(path, sources)
        if not check:
            path.write_text(expected, encoding="utf-8")
        elif path.read_text(encoding="utf-8") != expected:
            stale.append(path.relative_to(ROOT).as_posix())
    return stale


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--watch-only", action="store_true")
    parser.add_argument("--export", type=Path, help="Private handout under ignored .local")
    arguments = parser.parse_args()
    path = ROOT / "deploy/services.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    refresh(document, check=arguments.check, images=not arguments.watch_only)
    if not arguments.check:
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    if arguments.export:
        target = arguments.export.resolve()
        if not target.is_relative_to(ROOT / ".local"):
            raise ValueError("Operator handout must stay in ignored .local directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(export_text(document), encoding="utf-8")
    print("Verified Briareus service ownership and directory watches.")


if __name__ == "__main__":
    main()
