"""Own the isolated Briareus V1 local stack without changing existing Docker projects."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local" / "bri-v1"
PROJECT_PREFIX = "briareus-v1"


@dataclass(frozen=True, slots=True)
class LocalService:
    name: str
    compose: Path
    fixture: bool = False


def catalog() -> tuple[LocalService, ...]:
    document: object = json.loads((ROOT / "deploy/services.json").read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("services"), list):
        raise ValueError("Invalid Briareus service catalog")
    services: list[LocalService] = []
    fixtures = document.get("fixtures", [])
    if not isinstance(fixtures, list):
        raise ValueError("Invalid Briareus fixture catalog")
    for item in [*document["services"], *fixtures]:
        if not isinstance(item, dict):
            raise ValueError("Invalid Briareus service entry")
        name, relative = item.get("name"), item.get("compose")
        if not isinstance(name, str) or not isinstance(relative, str):
            raise ValueError("Invalid Briareus service paths")
        services.append(LocalService(name, ROOT / relative, item in fixtures))
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
    ensure_deployment_environment(runtime)
    ensure_native_environment(runtime)
    ensure_dependency_environment(runtime)
    print(f"Local state ready: {STATE}; existing credentials preserved.")


def ensure_native_environment(runtime: Path) -> None:
    existing = runtime.read_text(encoding="utf-8")
    values = (
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


def ensure_dependency_environment(runtime: Path) -> None:
    values = runtime_values(runtime)
    additions = (
        ("POSTGRES_USERNAME", "postgres"),
        ("POSTGRES_DATABASE", "bri"),
        ("POSTGRES_PASSWORD", secrets.token_urlsafe(48)),
        ("VALKEY_USERNAME", "default"),
        ("VALKEY_PASSWORD", secrets.token_urlsafe(48)),
        ("BRI_RUNTIME_BASE", "bri-v1-runtime-base:local"),
        ("MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,gateway:*"),
        ("MCP_ALLOWED_ORIGINS", "http://localhost:18080,http://127.0.0.1:18080"),
    )
    with runtime.open("a", encoding="utf-8") as output:
        for key, value in additions:
            if key not in values:
                output.write(f"{key}={value}\n")


def runtime_values(runtime: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in runtime.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )


def ensure_deployment_environment(runtime: Path) -> None:
    """Upgrade local configuration without changing credentials or volume identity."""
    values = runtime_values(runtime)
    for old, new in (
        ("OTEL_ENVIRONMENT", "DEPLOYMENT_ENVIRONMENT"),
        ("OTLP_ENDPOINT", "OTEL_ENDPOINT"),
        ("OTLP_BEARER_TOKEN", "OTEL_BEARER_TOKEN"),
    ):
        old_value = values.get(old)
        if old == "OTEL_ENVIRONMENT" and old_value == "local":
            old_value = "development"
        if old in values and new in values and old_value != values[new]:
            raise ValueError(f"Conflicting {old}/{new}; resolve explicitly before migration")
        if old in values:
            assert old_value is not None
            values[new] = old_value
            values.pop(old)
    values.setdefault("DEPLOYMENT_ENVIRONMENT", "development")
    if values["DEPLOYMENT_ENVIRONMENT"] not in {"development", "production", "staging", "test"}:
        raise ValueError("Invalid DEPLOYMENT_ENVIRONMENT; configuration was not rewritten")
    if values.get("OTEL_NAMESPACE") in {None, "bri-v1"}:
        values["OTEL_NAMESPACE"] = "briareus"
    text = runtime.read_text(encoding="utf-8")
    text = re.sub(r"^OTEL_NAMESPACE=bri-v1$", "OTEL_NAMESPACE=briareus", text, flags=re.MULTILINE)
    for key in ("OTEL_ENVIRONMENT", "OTLP_ENDPOINT", "OTLP_BEARER_TOKEN"):
        text = re.sub(rf"^{key}=.*\n?", "", text, flags=re.MULTILINE)
    for key in ("DEPLOYMENT_ENVIRONMENT", "OTEL_ENDPOINT", "OTEL_BEARER_TOKEN", "OTEL_NAMESPACE"):
        if key in values and not any(line.startswith(key + "=") for line in text.splitlines()):
            text = text.rstrip("\n") + f"\n{key}={values[key]}\n"
    runtime.write_text(text, encoding="utf-8")


def deployment_environment() -> str:
    values = runtime_values(STATE / "runtime.env")
    environment = os.environ.get("DEPLOYMENT_ENVIRONMENT", values.get("DEPLOYMENT_ENVIRONMENT", ""))
    if environment not in {"development", "production", "staging", "test"}:
        raise ValueError("DEPLOYMENT_ENVIRONMENT must be development, production, staging or test")
    return environment


def compose_command(service: LocalService) -> list[str]:
    environment = deployment_environment()
    if environment != "development":
        raise ValueError(
            "The local launcher preserves development volumes; use generic Compose elsewhere"
        )
    command = [
        "docker",
        "compose",
        "--project-name",
        f"{PROJECT_PREFIX}-{environment}-{service.name}",
        "--env-file",
        str(STATE / "runtime.env"),
    ]
    identity = STATE / "identity.env"
    if identity.exists():
        command.extend(["--env-file", str(identity)])
    command.extend(["--file", str(service.compose)])
    local = service.compose.with_name("docker-compose.local.yaml")
    if not service.fixture and local.is_file():
        command.extend(["--file", str(local)])
    return command


def compose(service: LocalService, arguments: list[str]) -> None:
    run([*compose_command(service), *arguments])


def networks() -> None:
    environment = deployment_environment()
    for suffix in ("private",):
        name = f"{PROJECT_PREFIX}-{environment}-{suffix}"
        check = subprocess.run(
            ["docker", "network", "inspect", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if check.returncode:
            run([
                "docker", "network", "create", "--label", "bri.version=1",
                "--label", f"deployment.environment={environment}", name,
            ])


def selected(names: list[str]) -> tuple[LocalService, ...]:
    services = catalog()
    missing = set(names) - {service.name for service in services}
    if missing:
        raise ValueError("Unknown services: " + ", ".join(sorted(missing)))
    return tuple(
        service
        for service in services
        if service.name in names or (not names and not service.fixture)
    )


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
    require_legacy_stack_stopped()
    networks()
    for service in selected(["dependencies"]):
        compose(service, ["up", "-d", "--wait", "--wait-timeout", "300"])


def bootstrap_identity(_names: list[str]) -> None:
    run([sys.executable, "scripts/bootstrap_zitadel.py", "--state-dir", str(STATE)])


def start_identity_fixture(_names: list[str]) -> None:
    init()
    require_legacy_stack_stopped()
    compose(selected(["identity-test"])[0], ["up", "-d", "--wait", "--wait-timeout", "300"])


def build_dependencies(_names: list[str]) -> None:
    build_base()


def build_units(names: list[str]) -> None:
    init()
    units = selected(names)
    if any(not service.fixture for service in units):
        build_base()
    for service in units:
        if not service.fixture:
            compose(service, ["build"])


def start_units(names: list[str]) -> None:
    require_legacy_stack_stopped()
    networks()
    for service in selected(names):
        timeout = "300" if service.name == "dependencies" or service.fixture else "180"
        compose(service, ["up", "-d", "--wait", "--wait-timeout", timeout])


def require_legacy_stack_stopped() -> None:
    """A new project may never open volumes while the old project still owns them."""
    active = subprocess.check_output(
        ["docker", "ps", "--filter", "label=com.docker.compose.project=bri-v1-local", "--quiet"],
        text=True,
    )
    if active.strip():
        raise ValueError("Stop the old bri-v1-local stack before starting replacement owners")


def stop_units(names: list[str]) -> None:
    for service in selected(names):
        compose(service, ["stop"])


def validate_units(names: list[str]) -> None:
    for service in selected(names):
        compose(service, ["config", "--quiet"])


def show_status(_names: list[str]) -> None:
    for service in catalog():
        project = f"{PROJECT_PREFIX}-{deployment_environment()}-{service.name}"
        run([
            "docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={project}",
            "--format", "{{.Names}}\t{{.Status}}",
        ])
    print(
        "Dependencies are one deployment with five containers. ZITADEL is external; "
        "identity-test is an optional isolated test fixture outside the Briareus network."
    )


_ACTIONS: dict[str, Callable[[list[str]], None]] = {
    "init": initialize,
    "dependencies": start_dependencies,
    "identity-bootstrap": bootstrap_identity,
    "identity-test": start_identity_fixture,
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
