"""Verify service-owned Python builds and their restricted Docker contexts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEGIN = "# BEGIN BRIAREUS PYTHON RUNTIME"
END = "# END BRIAREUS PYTHON RUNTIME"
SOURCE_BEGIN = "# BEGIN BRIAREUS SOURCE PACKAGES"
SOURCE_END = "# END BRIAREUS SOURCE PACKAGES"


def runtime_stage(owner: str) -> str:
    """Each image resolves only its own frozen third-party dependency manifest."""
    system_packages = []
    if (ROOT / owner / "system-packages.txt").is_file():
        system_packages = [
            f"COPY {owner}/system-packages.txt /tmp/service-packages.txt",
            "RUN apt-get update && xargs -r apt-get install -y --no-install-recommends "
            "< /tmp/service-packages.txt && rm -rf /var/lib/apt/lists/* /tmp/service-packages.txt",
        ]
    return "\n".join(
        [
            BEGIN,
            "FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS python-runtime",
            "ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 "
            "UV_LINK_MODE=copy PYTHONPATH=/app/src",
            "WORKDIR /app",
            "RUN apt-get update && apt-get install -y --no-install-recommends "
            "curl ca-certificates gosu netcat-openbsd && rm -rf /var/lib/apt/lists/*",
            *system_packages,
            f"COPY {owner}/pyproject.toml {owner}/uv.lock ./",
            "RUN uv sync --frozen --no-dev --no-install-project",
            "RUN mkdir -p /var/lib/briareus/control-panel "
            "/workspace /browser/profile /home/agent /home/briareus && chown -R 1000:1000 "
            "/var/lib/briareus /workspace /browser /home/agent /home/briareus",
            "ENV HOME=/home/briareus",
            "EXPOSE 8000",
            'ENTRYPOINT ["/usr/sbin/gosu", "1000:1000"]',
            'CMD ["/app/.venv/bin/python", "-m", "briareus_service_runtime.asgi"]',
            END,
            "",
        ]
    )


def standalone_dockerfile(source: str, owner: str) -> str:
    if source.startswith(BEGIN):
        _, separator, source = source.partition(END + "\n")
        if not separator:
            raise ValueError("The Python runtime recipe is incomplete")
        source = source.lstrip("\n")
    return runtime_stage(owner) + source


def image_paths() -> tuple[Path, ...]:
    document = json.loads((ROOT / "deploy/services.json").read_text(encoding="utf-8"))
    paths = [
        ROOT / service["dockerfile"]
        for service in document["services"]
        if service.get("dockerfile")
    ]
    paths.extend(
        ROOT / image["dockerfile"]
        for service in document["services"]
        for image in service.get("source_images", [])
    )
    return tuple(sorted(set(paths)))


def context_inputs(source: str, owner: str) -> list[str]:
    inputs = [f"{owner}/pyproject.toml", f"{owner}/uv.lock"]
    if (ROOT / owner / "system-packages.txt").is_file():
        inputs.append(f"{owner}/system-packages.txt")
    inside = False
    for line in source.splitlines():
        if line == SOURCE_BEGIN:
            inside = True
        elif line == SOURCE_END:
            inside = False
        elif inside and line.startswith("COPY "):
            inputs.append(line.split()[1].rstrip("/"))
    return inputs


def dockerignore(source: str, owner: str) -> str:
    """Allow only manifests and whole explicitly selected source packages."""
    lines = ["# Service-owned build context; generated from this Dockerfile.", "**"]
    included: set[str] = set()
    for item in context_inputs(source, owner):
        for parent in reversed(Path(item).parents):
            value = parent.as_posix()
            if value != "." and value not in included:
                lines.append(f"!{value}/")
                included.add(value)
        lines.append(f"!{item}")
        if not item.endswith((".toml", ".lock", ".txt")):
            lines.append(f"!{item}/**")
    lines.extend(
        [
            "**/__pycache__",
            "**/*.py[cod]",
            "**/.env",
            "**/.env.*",
            "**/node_modules",
            "**/.venv",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    paths = image_paths()
    if not paths:
        raise ValueError("No Briareus Python source images were found")
    for path in paths:
        owner = path.parent.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        expected = standalone_dockerfile(source, owner)
        ignore = path.with_name("Dockerfile.dockerignore")
        expected_ignore = dockerignore(expected, owner)
        if arguments.check:
            if (
                source != expected
                or not ignore.exists()
                or ignore.read_text(encoding="utf-8") != expected_ignore
            ):
                raise ValueError(f"Regenerate image recipe/context: {path.relative_to(ROOT)}")
        else:
            path.write_text(expected, encoding="utf-8", newline="\n")
            ignore.write_text(expected_ignore, encoding="utf-8", newline="\n")
    print(f"Verified {len(paths)} service-owned Python image recipes")


if __name__ == "__main__":
    main()
