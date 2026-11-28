"""Materialize explicit Coolify inputs from generic service deployment models."""

from __future__ import annotations

import argparse
import copy
import json
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast


class YamlCodec(Protocol):
    """The two public PyYAML operations used by this deployment adapter."""

    def safe_load(self, stream: str) -> object: ...

    def safe_dump(self, data: object, *, sort_keys: bool, allow_unicode: bool) -> str: ...


yaml = cast(YamlCodec, import_module("yaml"))

ROOT = Path(__file__).resolve().parents[1]


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Compose mapping must have string keys")
    return cast(dict[str, object], value)


def load_model(path: Path) -> dict[str, object]:
    return mapping(yaml.safe_load(path.read_text(encoding="utf-8")))


def resolved_model(path: Path) -> dict[str, object]:
    """Resolve owned service templates without a Docker daemon or CLI."""
    module = "scripts.compose_portable" if __package__ else "compose_portable"
    resolver = cast(Callable[[Path], dict[str, object]], import_module(module).resolve)
    return resolver(path)


def service_environment(service: dict[str, object], service_name: str) -> None:
    environment = environment_mapping(service.get("environment", {}))
    service["environment"] = environment
    if service_name == "gateway":
        # The generated URL is the single public-route authority. Keep the
        # legacy generic MCP_PUBLIC_BASE_URL outside the Coolify ENV contract.
        environment.pop("MCP_PUBLIC_BASE_URL", None)
        service["environment"] = {
            "SERVICE_URL_GATEWAY_8000": "/",
            **environment,
            "SERVICE_URL_GATEWAY": "${SERVICE_URL_GATEWAY}",
        }
    if service_name == "control-panel-api":
        environment["CONTROL_PANEL_PUBLIC_BASE_URL"] = "${MCP_PUBLIC_BASE_URL:?}"


def environment_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, list):
        return mapping(value)
    environment: dict[str, object] = {}
    for item in value:
        if not isinstance(item, str) or "=" not in item:
            raise ValueError("Compose environment inputs must declare explicit values")
        key, _, content = item.partition("=")
        environment[key] = content
    return environment


def destination_attachments(value: object) -> dict[str, object]:
    attachments = mapping(value)
    if "briareus-private" in attachments:
        attachments["default"] = attachments.pop("briareus-private")
    return {
        name: attachment if attachment is not None else {}
        for name, attachment in attachments.items()
    }


def service_destination(service: dict[str, object]) -> None:
    networks = service.get("networks", [])
    if isinstance(networks, list):
        names = [name for name in networks if name != "briareus-private"]
        if "briareus-private" in networks:
            names.append("default")
        service["networks"] = names
    else:
        service["networks"] = destination_attachments(networks)
    service.pop("ports", None)
    service.pop("secrets", None)
    build = service.get("build")
    if isinstance(build, dict):
        arguments = mapping(build.get("args", {}))
        arguments.pop("BRIAREUS_RUNTIME_BASE", None)
        if not arguments:
            build.pop("args", None)


def service_workspace(service: dict[str, object]) -> None:
    """Keep Coolify's literal mount target and every workspace consumer aligned."""
    volumes = service.get("volumes", [])
    if not isinstance(volumes, list):
        raise ValueError("Coolify service volumes must use a list")
    variable_mount = "workspace:${SERVER_MOUNT_PATH:-/workspace}"
    replaced: list[object] = []
    workspace = False
    for mount in volumes:
        replacement = mount
        if mount == variable_mount:
            replacement = "workspace:/workspace"
            workspace = True
        elif isinstance(mount, dict):
            configuration = mapping(mount)
            if (
                configuration.get("source") == "workspace"
                and configuration.get("target") == "${SERVER_MOUNT_PATH:-/workspace}"
            ):
                configuration["target"] = "/workspace"
                workspace = True
        replaced.append(replacement)
    if not workspace:
        return
    service["volumes"] = replaced
    environment = mapping(service.get("environment", {}))
    environment["SERVER_MOUNT_PATH"] = "/workspace"
    if "BROWSER_DOWNLOADS_PATH" in environment:
        environment["BROWSER_DOWNLOADS_PATH"] = "/workspace/browser/downloads"
    service["environment"] = environment


def coolify_model(generic: dict[str, object]) -> dict[str, object]:
    """Prepare parser inputs; deployment still requires verified network acceptance."""
    model = copy.deepcopy(generic)
    for name, value in mapping(model["services"]).items():
        service = mapping(value)
        service_environment(service, name)
        service_destination(service)
        service_workspace(service)
    networks = mapping(model.get("networks", {}))
    networks.pop("briareus-private", None)
    networks["default"] = {}
    model["networks"] = networks
    model.pop("secrets", None)
    coolify_volumes(mapping(model.get("volumes", {})))
    return model


def coolify_volumes(volumes: dict[str, object]) -> None:
    """Use supported volume-name interpolation; service ENV still requires the value."""
    for name, value in volumes.items():
        volume = mapping(value)
        physical_name = volume.get("name")
        if isinstance(physical_name, str):
            volume["name"] = physical_name.replace(
                "${DEPLOYMENT_ENVIRONMENT:?}", "${DEPLOYMENT_ENVIRONMENT}"
            )
        if name in {"workspace", "browser-profile", "browser-transfers"}:
            volume["external"] = True
            if not isinstance(physical_name, str):
                raise ValueError("Shared Coolify volumes must declare their physical name")


def rendered_model(path: Path) -> str:
    return (
        "# Generated by scripts/briareus_coolify.py; edit the generic owner and regenerate.\n"
        "# Verify the actual Coolify parser, Destination and public routes before rollout.\n"
        + yaml.safe_dump(coolify_model(resolved_model(path)), sort_keys=False, allow_unicode=True)
    )


def native_preview_model(path: Path) -> str:
    """Derive a private preview from the same native Gateway runtime owner."""
    generic = resolved_model(path)
    model = coolify_model(generic)
    service = mapping(mapping(model["services"])["gateway"])
    environment = mapping(service["environment"])
    environment.pop("SERVICE_URL_GATEWAY_8000")
    environment.pop("SERVICE_URL_GATEWAY")
    environment["MCP_PUBLIC_BASE_URL"] = "${MCP_PUBLIC_BASE_URL:?}"
    environment["GATEWAY_PRIVATE_PREVIEW"] = "true"
    service.pop("command")
    service["image"] = "briareus-v1-gateway-preview:local"
    service["mem_limit"] = "${GATEWAY_PREVIEW_MEMORY_LIMIT:-256m}"
    model["services"] = {"gateway-preview": service}
    return (
        "# Generated from the native Gateway runtime; private preview only.\n"
        "# No public ingress, published host port or live Gateway DNS alias.\n"
        + yaml.safe_dump(model, sort_keys=False, allow_unicode=True)
    )


def materialize(target: Path, expected: str, *, check: bool) -> None:
    if check:
        if target.read_text(encoding="utf-8") != expected:
            raise ValueError(f"Coolify entrypoint is stale: {target.relative_to(ROOT)}")
    else:
        target.write_text(expected, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    catalog = json.loads((ROOT / "deploy/services.json").read_text(encoding="utf-8"))
    paths = [ROOT / service["compose"] for service in catalog["services"]]
    # The native candidate stays out of the live catalog until promotion.
    candidate = ROOT / "services/gateway-rust/docker-compose.yaml"
    if candidate not in paths:
        paths.append(candidate)
    for path in paths:
        materialize(
            path.with_name("docker-compose.coolify.yaml"),
            rendered_model(path),
            check=arguments.check,
        )
    materialize(
        candidate.with_name("docker-compose.preview.yaml"),
        native_preview_model(candidate),
        check=arguments.check,
    )


if __name__ == "__main__":
    main()
