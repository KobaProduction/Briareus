"""Approved definitions and immutable release publication rules."""

import re
from dataclasses import dataclass, replace
from uuid import UUID


class CatalogError(Exception):
    """Stable rejection reason, adapted to the existing peer protocol outside."""


@dataclass(frozen=True, slots=True)
class BuildInputs:
    dockerfile: str
    paths: tuple[str, ...]
    platform: str
    build_args: tuple[tuple[str, str], ...] | None = None


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    memory_bytes: int
    cpu_millis: int
    pids: int

    def covers(self, minimum: "ResourceLimits") -> bool:
        return (
            self.memory_bytes >= minimum.memory_bytes
            and self.cpu_millis >= minimum.cpu_millis
            and self.pids >= minimum.pids
        )


@dataclass(frozen=True, slots=True)
class ArtifactDefinition:
    key: str
    name: str
    node_adapter: bool
    lifecycle: str
    workspace: bool
    storage_purpose: str
    inputs: BuildInputs
    minimum_limits: ResourceLimits
    default_limits: ResourceLimits


@dataclass(frozen=True, slots=True)
class LogicalModule:
    key: str
    name: str
    components: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    key: str
    enabled: bool
    inputs: BuildInputs | None


@dataclass(frozen=True, slots=True)
class ReleaseSummary:
    id: str
    module: str
    source_commit: str
    input_fingerprint: str
    image: str | None
    platform: str
    state: str
    created_at: str


@dataclass(frozen=True, slots=True)
class PublishedRelease:
    release: ReleaseSummary


@dataclass(frozen=True, slots=True)
class Publication:
    id: UUID
    module: str
    source_commit: str
    input_fingerprint: str
    image: str
    platform: str

    def __post_init__(self) -> None:
        if self.id.version != 4 or not self.module:
            raise CatalogError("Invalid publication")
        if not hex_digest(self.source_commit, 40) or not hex_digest(self.input_fingerprint, 64):
            raise CatalogError("Invalid publication")
        if self.platform != "linux/amd64" or len(self.image) > 512:
            raise CatalogError("Invalid publication")
        if re.fullmatch(r"[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}", self.image) is None:
            raise CatalogError("Invalid publication")


@dataclass(frozen=True, slots=True)
class PublicationIdentity:
    operation_uuid: UUID
    actor_uuid: UUID
    project_uuid: UUID
    fingerprint: str


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    actor_scope: str
    project_scope: str
    fingerprint: str
    state: str
    encrypted_outcome: str | None

    def require_matches(self, identity: PublicationIdentity) -> None:
        if (self.actor_scope, self.project_scope, self.fingerprint, self.state) != (
            str(identity.actor_uuid),
            str(identity.project_uuid),
            identity.fingerprint,
            "completed",
        ):
            raise CatalogError("Publication operation conflicts")


@dataclass(frozen=True, slots=True)
class PublicationReplay:
    fingerprint: str
    result: PublishedRelease


def reviewed_upgrade(artifact: StoredArtifact, definition: ArtifactDefinition) -> bool:
    """Accept only the explicitly reviewed radare2 source-closure addition."""
    if artifact.key != "reverse" or definition.key != "reverse" or not artifact.enabled:
        return False
    added = "hands/radare2/src/radare2_hand/**"
    if definition.inputs.paths.count(added) != 1:
        return False
    previous = replace(
        definition.inputs, paths=tuple(path for path in definition.inputs.paths if path != added)
    )
    return artifact.inputs == previous


def require_approved_artifact(artifact: StoredArtifact, definition: ArtifactDefinition) -> bool:
    if artifact.enabled and artifact.inputs == definition.inputs:
        return False
    if reviewed_upgrade(artifact, definition):
        return True
    raise CatalogError("Artifact definition changed; explicit approval required")


def require_publishable(
    definition: ArtifactDefinition, publication: Publication, registries: tuple[str, ...]
) -> None:
    if publication.module != definition.key:
        raise CatalogError("Unknown deployable module")
    if not definition.node_adapter:
        raise CatalogError("This Hand's node effect adapter is not ready")
    if publication.image.split("/", 1)[0] not in registries:
        raise CatalogError("Image registry not approved for publication")


def require_deployable(
    release: ReleaseSummary, artifact: StoredArtifact, definition: ArtifactDefinition
) -> None:
    if (
        release.state != "published"
        or release.image is None
        or release.platform != "linux/amd64"
        or release.module != definition.key
        or not artifact.enabled
        or not definition.node_adapter
        or artifact.inputs != definition.inputs
    ):
        raise CatalogError("Approved published node adapter required")


def hex_digest(value: str, length: int) -> bool:
    return len(value) == length and all(character in "0123456789abcdef" for character in value)
