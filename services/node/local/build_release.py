"""Build from an exact local Git snapshot, publish locally, record immutable identity.

Uses a temporary Git index; main, the working checkout and user's index are unchanged.
No CI image build, public registry, secret build arguments or source task files.
"""

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services"))
sys.path.insert(0, str(ROOT / "shared"))
from node.local.installation_identity import InstallationIdentity  # noqa: E402 -- direct CLI source bootstrap
from node_protocol.catalog import ARTIFACTS, ArtifactBuildInputs  # noqa: E402 -- direct CLI source bootstrap


class BuildPublication(BaseModel):
    id: UUID
    module: str
    source_commit: str
    input_fingerprint: str
    platform: str
    image: str
    build_args: dict[str, str] | None = None


class BuildxMetadata(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    digest: str = Field(default="", alias="containerimage.digest")


class _BuildArguments(argparse.Namespace):
    module: str


@dataclass(frozen=True, slots=True)
class _BuildPlan:
    module: str
    inputs: ArtifactBuildInputs
    registry_host: str
    paths: tuple[str, ...]
    reference: str


@dataclass(frozen=True, slots=True)
class _BuildSnapshot:
    commit: str
    fingerprint: str
    build_args: dict[str, str]


def run(
    args: Sequence[str], *, env: Mapping[str, str] | None = None, data: bytes | None = None
) -> bytes:
    value = subprocess.run(args, cwd=ROOT, env=env, input=data, capture_output=True, check=False)  # noqa: S603 -- fixed Git/Docker argv; no shell
    if value.returncode:
        raise RuntimeError(value.stderr.decode(errors="replace")[-3000:])
    return value.stdout


class _GitSnapshot(NamedTuple):
    tree: str
    listing: bytes


def _snapshot_inputs(paths: Sequence[str], env: Mapping[str, str]) -> _GitSnapshot:
    run(["git", "read-tree", "HEAD"], env=env)
    run(["git", "add", "-A", "--", *paths], env=env)
    tree = run(["git", "write-tree"], env=env).decode().strip()
    listing = run(["git", "ls-tree", "-rz", tree, "--", *paths])
    for entry in listing.split(b"\0"):
        if entry and not entry.startswith((b"100644 blob ", b"100755 blob ")):
            raise ValueError("Build inputs must be regular Git files")
    return _GitSnapshot(tree, listing)


def _require_build_arguments(build_args: Mapping[str, str]) -> None:
    if any(
        not re.fullmatch(r"[A-Z][A-Z0-9_]*", name)
        or not re.fullmatch(r"localhost:5500/briareus/[a-z0-9_-]+@sha256:[a-f0-9]{64}", value)
        for name, value in build_args.items()
    ):
        raise ValueError("Only immutable approved local image build inputs are allowed")


def _snapshot_commit(
    snapshot: _GitSnapshot,
    paths: Sequence[str],
    reference: str,
    module: str,
) -> str:
    previous = subprocess.run(  # noqa: S603 -- fixed local Git reference query; no shell
        ["git", "rev-parse", "--verify", reference],  # noqa: S607 -- operator Git resolved from PATH
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if (
        previous.returncode == 0
        and run(["git", "ls-tree", "-rz", previous.stdout.decode().strip(), "--", *paths])
        == snapshot.listing
    ):
        commit = previous.stdout.decode().strip()
    else:
        commit = (
            run(
                [
                    "git",
                    "-c",
                    "user.name=Briareus local build",
                    "-c",
                    "user.email=local-build@invalid",
                    "commit-tree",
                    snapshot.tree,
                    "-p",
                    "HEAD",
                ],
                data=("Local build snapshot: " + module + "\n").encode(),
            )
            .decode()
            .strip()
        )
        run(["git", "update-ref", reference, commit])
    return commit


def _module_argument() -> str:
    parser = argparse.ArgumentParser()
    parser.add_argument("module", choices=[*ARTIFACTS, "node"])
    arguments = _BuildArguments()
    parser.parse_args(namespace=arguments)
    return arguments.module


def _build_inputs(module: str) -> ArtifactBuildInputs:
    if module == "node":
        return ArtifactBuildInputs(
            dockerfile="services/node/Dockerfile",
            platform="linux/amd64",
            paths=[
                "services/node/Dockerfile",
                "services/node/Dockerfile.dockerignore",
                "services/node/pyproject.toml",
                "services/node/uv.lock",
                "services/node/src/**",
                "shared/node_protocol/**",
                "shared/gateway_runtime/**",
                "shared/service_runtime/__init__.py",
                "shared/service_runtime/runtime_binding.py",
            ],
        )
    definition = ARTIFACTS[module]
    if not definition.node_adapter:
        raise ValueError("An implemented node adapter is required for publication")
    return definition.inputs


def _prepare_build(module: str) -> _BuildPlan:
    inputs = _build_inputs(module)
    installation = InstallationIdentity.model_validate_json(
        (ROOT / ".local/briareus/secrets/node/installation.json").read_bytes()
    )
    return _BuildPlan(
        module,
        inputs,
        installation.registry_host,
        tuple(path.removesuffix("/**") for path in inputs.paths),
        "refs/heads/codex/local-build-" + module,
    )


def _input_fingerprint(listing: bytes, build_args: Mapping[str, str]) -> str:
    fingerprint_input = listing
    if build_args:
        fingerprint_input += (
            b"\0build_args\0"
            + json.dumps(build_args, sort_keys=True, separators=(",", ":")).encode()
        )
    return hashlib.sha256(fingerprint_input).hexdigest()


def _prepare_snapshot(plan: _BuildPlan, temporary: Path) -> _BuildSnapshot:
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str(temporary / "index")
    snapshot = _snapshot_inputs(plan.paths, env)
    build_args = plan.inputs.build_args or {}
    _require_build_arguments(build_args)
    fingerprint = _input_fingerprint(snapshot.listing, build_args)
    commit = _snapshot_commit(snapshot, plan.paths, plan.reference, plan.module)
    return _BuildSnapshot(commit, fingerprint, build_args)


def _build_snapshot(plan: _BuildPlan, snapshot: _BuildSnapshot, temporary: Path) -> str:
    context = temporary / "context"
    context.mkdir()
    archive = run(["git", "archive", snapshot.commit, "--", *plan.paths])
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(context, filter="data")
    tag = "localhost:5500/briareus/" + plan.module + ":local"
    metadata = temporary / "build-metadata.json"
    # Publish directly without unpacking a second copy into Desktop's image
    # store. The dedicated Node engine pulls this exact registry digest.
    build_command = [
        "docker",
        "buildx",
        "build",
        "--platform",
        plan.inputs.platform,
        "-t",
        tag,
        "--output",
        "type=image,push=true,store=false,unpack=false",
        "--metadata-file",
        str(metadata),
    ]
    for name, value in sorted(snapshot.build_args.items()):
        build_command += ["--build-arg", name + "=" + value]
    run([*build_command, "-f", str(context / plan.inputs.dockerfile), str(context)])
    digest = BuildxMetadata.model_validate_json(metadata.read_text(encoding="utf-8")).digest
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("Exact published image digest required")
    return digest


def _publication(plan: _BuildPlan, snapshot: _BuildSnapshot, digest: str) -> BuildPublication:
    return BuildPublication(
        id=uuid4(),
        module=plan.module,
        source_commit=snapshot.commit,
        input_fingerprint=snapshot.fingerprint,
        platform=plan.inputs.platform,
        image=plan.registry_host + ":5500/briareus/" + plan.module + "@" + digest,
        build_args=snapshot.build_args or None,
    )


def _publish_record(publication: BuildPublication) -> None:
    output = ROOT / ".local/briareus/secrets/node/releases"
    output.mkdir(mode=0o700, exist_ok=True)
    serialized = publication.model_dump(mode="json", exclude_none=True)
    (output / (publication.module + ".json")).write_text(
        json.dumps(serialized, indent=2), encoding="utf-8"
    )
    print(json.dumps(serialized))


def main() -> None:
    plan = _prepare_build(_module_argument())
    with tempfile.TemporaryDirectory(prefix="briareus-release-") as directory:
        temporary = Path(directory)
        snapshot = _prepare_snapshot(plan, temporary)
        digest = _build_snapshot(plan, snapshot, temporary)
        _publish_record(_publication(plan, snapshot, digest))


if __name__ == "__main__":
    main()
