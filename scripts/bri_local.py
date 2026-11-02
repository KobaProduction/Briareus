"""Own the isolated BRI V1 local stack without changing existing Docker projects."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local" / "bri-v1"
PROJECT = "bri-v1-local"


@dataclass(frozen=True, slots=True)
class LocalService:
    name: str
    compose: Path
    optional: bool = False


def catalog() -> tuple[LocalService, ...]:
    document: object = json.loads((ROOT / "deploy/services.json").read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("services"), list):
        raise ValueError("Invalid BRI service catalog")
    services: list[LocalService] = []
    for item in document["services"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid BRI service entry")
        name, relative = item.get("name"), item.get("compose")
        if not isinstance(name, str) or not isinstance(relative, str):
            raise ValueError("Invalid BRI service paths")
        optional = item.get("optional", False)
        if not isinstance(optional, bool):
            raise ValueError("Invalid BRI optional service flag")
        services.append(LocalService(name, ROOT / relative, optional))
    return tuple(services)


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def init() -> None:
    secret_dir = STATE / "secrets"
    secret_dir.mkdir(parents=True, exist_ok=True)
    (STATE / "zitadel-bootstrap").mkdir(exist_ok=True)
    runtime = STATE / "runtime.env"
    if not runtime.exists():
        values = (
            ("BRI_LOCAL_STATE_DIR", STATE.as_posix()),
            ("CONTROL_PANEL_SERVICE_TOKEN", secrets.token_urlsafe(48)),
            (
                "CONTROL_PANEL_ENCRYPTION_KEY",
                base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
            ),
            ("CONTROL_PANEL_SESSION_SECRET", secrets.token_urlsafe(48)),
            ("BROWSER_CONTROL_TOKEN", secrets.token_urlsafe(48)),
            ("ZITADEL_MASTERKEY", secrets.token_hex(16)),
            ("ZITADEL_POSTGRES_PASSWORD", secrets.token_urlsafe(48)),
            ("ZITADEL_SESSION_COOKIE_SECRET", secrets.token_hex(16)),
            ("CONTROL_PANEL_PUBLIC_BASE_URL", "http://localhost:18080"),
            ("MCP_PUBLIC_BASE_URL", "http://localhost:18080"),
            ("TZ", "Europe/Moscow"),
        )
        runtime.write_text("".join(f"{key}={value}\n" for key, value in values), encoding="utf-8")
        os.chmod(runtime, 0o600)
    signing = secret_dir / "mcp-oauth-signing-key"
    if not signing.exists():
        signing.write_text(secrets.token_urlsafe(64), encoding="utf-8")
        os.chmod(signing, 0o600)
    introspection = secret_dir / "mcp-oauth-introspection-token"
    if not introspection.exists():
        introspection.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        os.chmod(introspection, 0o600)
    ensure_native_environment(runtime)
    print(f"Local state ready: {STATE}; existing credentials preserved.")


def ensure_native_environment(runtime: Path) -> None:
    existing = runtime.read_text(encoding="utf-8")
    values = (
        ("BRI_SOURCE_DIR", ROOT.as_posix()),
        ("BRI_GHIDRA_SOURCE_DIR", (ROOT / ".local/dependencies/ghidra-mcp").as_posix()),
        ("BRI_GHIDRA_ENGINE_TOKEN", secrets.token_urlsafe(48)),
    )
    additional = "".join(
        f"{key}={value}\n"
        for key, value in values
        if not any(line.startswith(key + "=") for line in existing.splitlines())
    )
    if additional:
        with runtime.open("a", encoding="utf-8") as output:
            output.write(additional)


def compose_command(service: LocalService) -> list[str]:
    command = [
        "docker",
        "compose",
        "--project-name",
        PROJECT,
        "--env-file",
        str(STATE / "runtime.env"),
    ]
    identity = STATE / "identity.env"
    if identity.exists():
        command.extend(["--env-file", str(identity)])
    if service.optional:
        command.extend(["--profile", service.name])
    command.extend(["--file", str(service.compose)])
    return command


def compose(service: LocalService, arguments: list[str]) -> None:
    run([*compose_command(service), *arguments])


def networks() -> None:
    for name in ("bri-v1-private", "bri-v1-browser-private"):
        check = subprocess.run(
            ["docker", "network", "inspect", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if check.returncode:
            run(["docker", "network", "create", "--label", "bri.version=1", name])


def selected(names: list[str]) -> tuple[LocalService, ...]:
    services = catalog()
    missing = set(names) - {service.name for service in services}
    if missing:
        raise ValueError("Unknown services: " + ", ".join(sorted(missing)))
    return tuple(
        service
        for service in services
        if service.name in names or (not names and not service.optional)
    )


def native_context(service: LocalService) -> Path:
    value: object = json.loads(
        subprocess.check_output(
            [*compose_command(service), "config", "--format", "json"], text=True
        )
    )
    for key in ("services", "ghidra-engine", "build", "context"):
        if not isinstance(value, dict):
            raise ValueError("Invalid native Ghidra build context")
        value = value.get(key)
    if not isinstance(value, str):
        raise ValueError("Native Ghidra build context must be a path")
    return Path(value)


def verify_native_source(service: LocalService) -> None:
    source = native_context(service)
    pin: object = json.loads((ROOT / "deploy/dependencies/ghidra-native/source.json").read_text())
    if not isinstance(pin, dict) or not isinstance(pin.get("revision"), str):
        raise ValueError("Invalid native Ghidra source pin")
    expected = pin["revision"]
    actual = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    project = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "--show-toplevel"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain"], text=True
    ).strip()
    if actual != expected or Path(project).resolve() != source.resolve() or dirty:
        raise ValueError("Native Ghidra requires the clean exact checkout pinned in source.json")


def build_base() -> None:
    digest = hashlib.sha256()
    for name in ("Dockerfile", "pyproject.toml", "uv.lock"):
        digest.update(name.encode())
        digest.update((ROOT / name).read_bytes())
    fingerprint = digest.hexdigest()
    existing = subprocess.run(
        [
            "docker",
            "image",
            "inspect",
            "bri-v1-runtime-base:local",
            "--format",
            '{{index .Config.Labels "bri.dependency-source"}}',
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if existing.returncode == 0 and existing.stdout.strip() == fingerprint:
        print("Pinned dependency image is unchanged; reusing it.")
        return
    run(
        [
            "docker",
            "build",
            "-t",
            "bri-v1-runtime-base:local",
            "--label",
            f"bri.dependency-source={fingerprint}",
            ".",
        ]
    )


def initialize(_names: list[str]) -> None:
    init()


def start_dependencies(_names: list[str]) -> None:
    init()
    networks()
    for service in selected(["dependencies", "identity"]):
        compose(service, ["up", "-d", "--wait", "--wait-timeout", "300"])


def bootstrap_identity(_names: list[str]) -> None:
    run([sys.executable, "scripts/bootstrap_zitadel.py", "--state-dir", str(STATE)])


def build_dependencies(_names: list[str]) -> None:
    build_base()


def build_units(names: list[str]) -> None:
    units = selected(names)
    if any(not service.optional for service in units):
        build_base()
    for service in units:
        if service.name == "native-ghidra":
            verify_native_source(service)
        if service.name not in {"dependencies", "identity"}:
            compose(service, ["build"])


def start_units(names: list[str]) -> None:
    networks()
    for service in selected(names):
        timeout = "300" if service.optional else "180"
        compose(service, ["up", "-d", "--wait", "--wait-timeout", timeout])


def stop_units(names: list[str]) -> None:
    for service in selected(names):
        compose(service, ["stop"])


def validate_units(names: list[str]) -> None:
    for service in selected(names):
        compose(service, ["config", "--quiet"])


def show_status(_names: list[str]) -> None:
    run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
            "--format",
            "{{.Names}}\t{{.Status}}",
        ]
    )
    print(
        "Native Ghidra is an optional independent backend. Proxy TCP health does not "
        "prove Analysis callability; verify the configured native MCP backend separately."
    )


_ACTIONS: dict[str, Callable[[list[str]], None]] = {
    "init": initialize,
    "dependencies": start_dependencies,
    "identity-bootstrap": bootstrap_identity,
    "base": build_dependencies,
    "build": build_units,
    "up": start_units,
    "stop": stop_units,
    "config": validate_units,
    "status": show_status,
}


def main() -> None:
    arguments = sys.argv[1:]
    action = arguments[0] if arguments else "status"
    handler = _ACTIONS.get(action)
    if handler is None:
        raise ValueError("Use one of: " + ", ".join(_ACTIONS))
    handler(arguments[1:])


if __name__ == "__main__":
    main()
