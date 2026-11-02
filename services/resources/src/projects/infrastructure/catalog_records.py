"""Validate JSON persistence/build definitions before mapping into typed records."""

import json

from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator

from node_protocol.catalog import Artifact
from projects.domain.module_catalog import ArtifactDefinition, BuildInputs, ResourceLimits

_REGISTRIES: TypeAdapter[list[str]] = TypeAdapter(list[str])


class InputPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dockerfile: str
    paths: tuple[str, ...]
    platform: str
    build_args: dict[str, str] | None = None

    def record(self) -> BuildInputs:
        arguments = None if self.build_args is None else tuple(sorted(self.build_args.items()))
        return BuildInputs(self.dockerfile, self.paths, self.platform, arguments)

    @model_validator(mode="after")
    def explicit_arguments(self) -> "InputPayload":
        if self.build_args is None and "build_args" in self.model_fields_set:
            raise ValueError("An explicitly null build argument contract is not approved")
        return self

    @classmethod
    def from_record(cls, inputs: BuildInputs) -> "InputPayload":
        if inputs.build_args is None:
            return cls(dockerfile=inputs.dockerfile, paths=inputs.paths, platform=inputs.platform)
        return cls(
            dockerfile=inputs.dockerfile,
            paths=inputs.paths,
            platform=inputs.platform,
            build_args=dict(inputs.build_args),
        )


def stored_inputs(value: InputPayload | None) -> BuildInputs | None:
    return value.record() if value is not None else None


def artifact_definition(source: Artifact) -> ArtifactDefinition:
    inputs = source.inputs
    minimum = source.minimum_limits
    default = source.default_limits
    return ArtifactDefinition(
        source.key,
        source.name,
        source.node_adapter,
        source.lifecycle,
        source.workspace,
        source.storage_purpose,
        BuildInputs(
            inputs.dockerfile,
            tuple(inputs.paths),
            inputs.platform,
            tuple(sorted(inputs.build_args.items())) if inputs.build_args is not None else None,
        ),
        ResourceLimits(minimum.memory_bytes, minimum.cpu_millis, minimum.pids),
        ResourceLimits(default.memory_bytes, default.cpu_millis, default.pids),
    )


def approved_registries(raw: str) -> tuple[str, ...]:
    try:
        return tuple(_REGISTRIES.validate_python(json.loads(raw), strict=True))
    except (ValueError, TypeError):
        return ()
