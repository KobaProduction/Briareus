"""Selector identity and exact supplied-field agreement for committed update retries."""

from dataclasses import dataclass
from uuid import UUID

from projects.domain.node_administration import NodeConflict


@dataclass(frozen=True)
class UpdateIntent:
    operation_uuid: UUID
    actor_uuid: UUID
    project_uuid: UUID
    placement_uuid: UUID
    release_uuid: UUID
    expected_sequence: int


@dataclass(frozen=True)
class UpdateReplayFields:
    target_matches: bool
    limits_match: bool | None
    configuration_match: bool | None
    project_workspace_match: bool | None


@dataclass(frozen=True)
class UpdateReplay:
    actor_uuid: UUID
    placement_uuid: UUID
    sequence: int

    def require_matches(self, intent: UpdateIntent, fields: UpdateReplayFields) -> None:
        # None means a field was omitted. Explicit null workspace is compared,
        # so omitting an attachment cannot silently turn into detaching it.
        if (
            self.actor_uuid != intent.actor_uuid
            or self.placement_uuid != intent.placement_uuid
            or self.sequence != intent.expected_sequence + 1
            or not fields.target_matches
            or fields.limits_match is False
            or fields.configuration_match is False
            or fields.project_workspace_match is False
        ):
            raise NodeConflict("Update operation identity conflicts")
