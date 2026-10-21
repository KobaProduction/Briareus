"""Bounded human management selectors; never raw Docker configuration."""
from typing import Literal
from pydantic import Field, UUID4, model_validator, model_serializer
from .models import Contract, ResourceLimits, ModuleConfiguration, WorkspaceMount

ModuleKey=Literal["files","terminal","web","svc","infrastructure","reverse","serena"]


class Publication(Contract):
    id: UUID4
    module: ModuleKey
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    input_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    image: str = Field(max_length=512,pattern=r"^[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}$")
    platform: Literal["linux/amd64"] = "linux/amd64"


class PlacementInput(Contract):
    id: UUID4
    node_uuid: UUID4
    release_uuid: UUID4
    name: str = Field(min_length=1,max_length=128)
    limits: ResourceLimits
    configuration: ModuleConfiguration | None = None
    project_workspace: WorkspaceMount | None = None

    @model_serializer(mode="wrap")
    def wire(self, handler):
        value = handler(self)
        if self.project_workspace is None:
            value.pop("project_workspace", None)
        return value


class PlacementUpdate(Contract):
    id: UUID4
    release_uuid: UUID4
    expected_sequence: int = Field(ge=1)
    limits: ResourceLimits | None = None
    configuration: ModuleConfiguration | None = None
    project_workspace: WorkspaceMount | None = None

    @model_serializer(mode="wrap")
    def wire(self, handler):
        value = handler(self)
        if self.project_workspace is None and "project_workspace" not in self.model_fields_set:
            value.pop("project_workspace", None)
        return value


class PlacementRecovery(Contract):
    id: UUID4
    expected_sequence: int = Field(strict=True,ge=1)


class ModuleCommand(Contract):
    action: Literal["catalog","publish","placements","place","update","reconcile","workspaces","ensure_workspace","recover"]
    publication: Publication | None = None
    placement: PlacementInput | None = None
    update: PlacementUpdate | None = None
    recover: PlacementRecovery | None = None
    node_uuid: UUID4 | None = None
    target_operation_uuid: UUID4 | None = None

    @model_validator(mode="after")
    def exact(self):
        populated={key for key,value in self.model_dump().items() if key!="action" and value is not None}
        allowed={"catalog":set(),"publish":{"publication"},"place":{"placement"},
            "recover":{"recover"},"update":{"update"},"placements":{"node_uuid"},"reconcile":{"target_operation_uuid"},
            "workspaces":{"node_uuid"},"ensure_workspace":{"node_uuid"}}[self.action]
        required=allowed-({"node_uuid"} if self.action=="placements" else set())
        if not required<=populated<=allowed:
            raise ValueError("Exact module command fields required")
        return self
