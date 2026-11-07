"""Own the isolated Briareus V1 local stack without changing existing Docker projects."""

from __future__ import annotations

import base64
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
LOCAL_CONFIGURATION = ROOT / ".local/briareus-development.json"


def local_configuration() -> dict[str, object]:
    if not LOCAL_CONFIGURATION.is_file():
        return {}
    value: object = json.loads(LOCAL_CONFIGURATION.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Invalid local Briareus configuration")
    return value


def state_directory() -> Path:
    configured = local_configuration().get("state_directory", ".local/briareus-v1")
    if not isinstance(configured, str):
        raise ValueError("Invalid local state directory")
    path = (ROOT / configured).resolve()
    if not path.is_relative_to(ROOT / ".local"):
        raise ValueError("Local state must remain inside ignored .local")
    return path


STATE = state_directory()
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
            ("BRIAREUS_LOCAL_STATE_DIR", STATE.as_posix()),
            ("BRIAREUS_SERVICE_TOKEN", secrets.token_urlsafe(48)),
            (
                "CONTROL_PANEL_ENCRYPTION_KEY",
                base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
            ),
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
    preserve_local_configuration(runtime)
    ensure_deployment_environment(runtime)
    ensure_dependency_environment(runtime)
    identity_routes(runtime)
    print(f"Local state ready: {STATE}; existing credentials preserved.")


def preserve_local_configuration(runtime: Path) -> None:
    """Keep historical local credentials and storage identities through source moves."""
    configuration = local_configuration()
    aliases = configuration.get("environment_aliases", {})
    overrides = configuration.get("volume_overrides", {})
    environment_overrides = configuration.get("environment_overrides", {})
    if not isinstance(environment_overrides, dict):
        raise ValueError("Invalid local environment overrides")
    if not isinstance(aliases, dict) or not isinstance(overrides, dict):
        raise ValueError("Invalid local compatibility configuration")
    values = runtime_values(runtime)
    additions = {"BRIAREUS_LOCAL_STATE_DIR": STATE.as_posix()}
    additions.update(_alias_additions(aliases, values))
    for name, value in {**overrides, **environment_overrides}.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError("Invalid local volume identity")
        additions[name] = value
    with runtime.open("a", encoding="utf-8") as output:
        for name, value in additions.items():
            if name not in values:
                output.write(f"{name}={value}\n")


def _alias_additions(aliases: dict[object, object], values: dict[str, str]) -> dict[str, str]:
    additions: dict[str, str] = {}
    for old, new in aliases.items():
        if isinstance(old, str) and isinstance(new, str) and old in values:
            if new in values and values[new] != values[old]:
                raise ValueError("Conflicting local configuration aliases")
            additions[new] = values[old]
    return additions


def identity_routes(runtime: Path) -> None:
    """Render local-only routing while preserving the configured issuer identity."""
    host = runtime_values(runtime).get("BRIAREUS_LOCAL_IDENTITY_HOST", "auth.briareus.localhost")
    if not host.endswith(".localhost") or not re.fullmatch(r"[A-Za-z0-9.-]+", host):
        raise ValueError("Local identity host must be a localhost subdomain")
    template = (ROOT / "tests/fixtures/zitadel/routes.yaml").read_text(encoding="utf-8")
    (STATE / "identity-routes.yaml").write_text(
        template.replace("auth.briareus.localhost", host), encoding="utf-8"
    )


def ensure_dependency_environment(runtime: Path) -> None:
    values = runtime_values(runtime)
    additions = (
        ("POSTGRES_USERNAME", "postgres"),
        ("POSTGRES_DATABASE", "briareus"),
        ("POSTGRES_PASSWORD", secrets.token_urlsafe(48)),
        ("VALKEY_USERNAME", "default"),
        ("VALKEY_PASSWORD", secrets.token_urlsafe(48)),
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
    if "CONTROL_PANEL_SERVICE_TOKEN" in values:
        previous = values["CONTROL_PANEL_SERVICE_TOKEN"]
        if values.get("BRIAREUS_SERVICE_TOKEN", previous) != previous:
            raise ValueError("Conflicting internal service tokens; resolve before configuration")
        values["BRIAREUS_SERVICE_TOKEN"] = previous
    _upgrade_observability_aliases(values)
    values.setdefault("DEPLOYMENT_ENVIRONMENT", "development")
    if values["DEPLOYMENT_ENVIRONMENT"] not in {"development", "production", "staging", "test"}:
        raise ValueError("Invalid DEPLOYMENT_ENVIRONMENT; configuration was not rewritten")
    if values.get("OTEL_NAMESPACE") in {None, "briareus-v1"}:
        values["OTEL_NAMESPACE"] = "briareus"
    text = runtime.read_text(encoding="utf-8")
    text = re.sub(
        r"^OTEL_NAMESPACE=briareus-v1$", "OTEL_NAMESPACE=briareus", text, flags=re.MULTILINE
    )
    for key in ("OTEL_ENVIRONMENT", "OTLP_ENDPOINT", "OTLP_BEARER_TOKEN"):
        text = re.sub(rf"^{key}=.*\n?", "", text, flags=re.MULTILINE)
    for key in (
        "DEPLOYMENT_ENVIRONMENT",
        "OTEL_ENDPOINT",
        "OTEL_BEARER_TOKEN",
        "OTEL_NAMESPACE",
        "BRIAREUS_SERVICE_TOKEN",
    ):
        if key in values and not any(line.startswith(key + "=") for line in text.splitlines()):
            text = text.rstrip("\n") + f"\n{key}={values[key]}\n"
    runtime.write_text(text, encoding="utf-8")


def _upgrade_observability_aliases(values: dict[str, str]) -> None:
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
            run(
                [
                    "docker",
                    "network",
                    "create",
                    "--label",
                    "briareus.version=1",
                    "--label",
                    f"deployment.environment={environment}",
                    name,
                ]
            )


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


def initialize(_names: list[str]) -> None:
    init()


def start_dependencies(_names: list[str]) -> None:
    init()
    require_legacy_stack_stopped()
    require_replaced_writers_stopped(["dependencies"])
    networks()
    for service in selected(["dependencies"]):
        compose(service, ["up", "-d", "--wait", "--wait-timeout", "300"])


def bootstrap_identity(_names: list[str]) -> None:
    command = [sys.executable, "scripts/bootstrap_zitadel.py", "--state-dir", str(STATE)]
    identity = STATE / "identity.env"
    if identity.is_file():
        issuer = runtime_values(identity).get("ZITADEL_ISSUER_URL")
        if issuer:
            command.extend(["--issuer", issuer])
    run(command)


def start_identity_fixture(_names: list[str]) -> None:
    init()
    require_legacy_stack_stopped()
    compose(selected(["identity-test"])[0], ["up", "-d", "--wait", "--wait-timeout", "300"])


def build_units(names: list[str]) -> None:
    init()
    units = selected(names)
    for service in units:
        if not service.fixture:
            compose(service, ["build"])


def start_units(names: list[str]) -> None:
    require_legacy_stack_stopped()
    units = selected(names)
    require_replaced_writers_stopped([service.name for service in units])
    networks()
    for service in units:
        timeout = "300" if service.name == "dependencies" or service.fixture else "180"
        compose(service, ["up", "-d", "--wait", "--wait-timeout", timeout])


def require_legacy_stack_stopped() -> None:
    """A new project may never open volumes while the old project still owns them."""
    projects = local_configuration().get("previous_projects", ["briareus-v1-local"])
    if not isinstance(projects, list) or not all(isinstance(name, str) for name in projects):
        raise ValueError("Invalid previous local project identities")
    for project in projects:
        active = subprocess.check_output(
            ["docker", "ps", "--filter", f"label=com.docker.compose.project={project}", "--quiet"],
            text=True,
        )
        if active.strip():
            raise ValueError(f"Stop the old {project} stack before starting replacement owners")


def require_replaced_writers_stopped(names: list[str]) -> None:
    """Guard shared-volume ownership only for the units being replaced."""
    configuration = local_configuration()
    replacements = configuration.get("replaced_projects", {})
    services = configuration.get("replaced_services", {})
    if not isinstance(services, dict):
        raise ValueError("Invalid local replacement services")
    if not isinstance(replacements, dict):
        raise ValueError("Invalid local replacement projects")
    for name in names:
        projects = replacements.get(name, [])
        if not isinstance(projects, list) or not all(isinstance(item, str) for item in projects):
            raise ValueError("Invalid local replacement project identities")
        for project in projects:
            _require_replaced_project_stopped(project, name)
        _require_previous_services_stopped(services.get(name, []), name)


def _require_replaced_project_stopped(project: str, name: str) -> None:
    active = subprocess.check_output(
        ["docker", "ps", "--filter", f"label=com.docker.compose.project={project}", "--quiet"],
        text=True,
    )
    if active.strip():
        raise ValueError(f"Stop {project} before starting the replacement {name} owner")


def _require_previous_services_stopped(previous_services: object, name: str) -> None:
    if not isinstance(previous_services, list):
        raise ValueError("Invalid previous service identities")
    for previous in previous_services:
        if not isinstance(previous, dict) or not all(
            isinstance(previous.get(key), str) and previous[key] for key in ("project", "service")
        ):
            raise ValueError("Invalid previous service identity")
        active = subprocess.check_output(
            [
                "docker",
                "ps",
                "--filter",
                f"label=com.docker.compose.project={previous['project']}",
                "--filter",
                f"label=com.docker.compose.service={previous['service']}",
                "--quiet",
            ],
            text=True,
        )
        if active.strip():
            raise ValueError(
                f"Stop the previous {previous['service']} container before "
                f"starting its replacement in {name}"
            )


def stop_units(names: list[str]) -> None:
    for service in selected(names):
        compose(service, ["stop"])


def validate_units(names: list[str]) -> None:
    for service in selected(names):
        compose(service, ["config", "--quiet"])


def show_status(_names: list[str]) -> None:
    for service in catalog():
        project = f"{PROJECT_PREFIX}-{deployment_environment()}-{service.name}"
        run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                "{{.Names}}\t{{.Status}}",
            ]
        )
    print(
        "Dependencies are one deployment with three containers. ZITADEL is external; "
        "identity-test is an optional isolated test fixture outside the Briareus network."
    )


_ACTIONS: dict[str, Callable[[list[str]], None]] = {
    "init": initialize,
    "dependencies": start_dependencies,
    "identity-bootstrap": bootstrap_identity,
    "identity-test": start_identity_fixture,
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
