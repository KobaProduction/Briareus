"""Safe Coolify metadata schemas. Credentials, variable values and file contents are excluded."""

from typing import Literal, Self

from pydantic import BaseModel, RootModel

from service_runtime.account_contracts import AccountConnectionSummary
from service_runtime.provider_identity import CoolifyTeamMetadata


class ApplicationMetadata(BaseModel):
    uuid: str | None = None
    name: str | None = None
    description: str | None = None
    status: str | None = None
    container_present: bool | None = None
    server_status: str | None = None
    git_repository: str | None = None
    git_branch: str | None = None
    git_commit_sha: str | None = None
    build_pack: str | None = None
    dockerfile_location: str | None = None
    docker_compose_location: str | None = None
    base_directory: str | None = None
    environment_id: int | None = None
    destination_id: int | None = None
    source_id: int | None = None
    compose_parsing_version: str | None = None
    is_raw_compose_deployment_enabled: bool | None = None
    include_source_commit_in_build: bool | None = None
    inject_build_args_to_dockerfile: bool | None = None
    disable_build_cache: bool | None = None
    is_git_shallow_clone_enabled: bool | None = None
    is_git_submodules_enabled: bool | None = None
    is_git_lfs_enabled: bool | None = None
    watch_paths: str | None = None
    ports_exposes: str | None = None
    fqdn: str | None = None
    restart_count: int | None = None
    restart_limit_reached: bool | None = None
    last_online_at: str | None = None
    last_restart_at: str | None = None
    last_restart_type: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class DeploymentMetadata(BaseModel):
    id: int | None = None
    deployment_uuid: str | None = None
    application_id: int | None = None
    application_name: str | None = None
    server_id: int | None = None
    server_name: str | None = None
    status: str | None = None
    commit: str | None = None
    commit_message: str | None = None
    force_rebuild: bool | None = None
    restart_only: bool | None = None
    rollback: bool | None = None
    pull_request_id: int | None = None
    is_api: bool | None = None
    is_webhook: bool | None = None
    created_at: str | None = None
    updated_at: str | None = None
    finished_at: str | None = None


TeamMetadata = CoolifyTeamMetadata


class ServerMetadata(BaseModel):
    uuid: str | None = None
    name: str | None = None
    description: str | None = None
    proxy_type: str | None = None
    server_role: str | None = None
    unreachable_count: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ServerResourceMetadata(BaseModel):
    uuid: str | None = None
    name: str | None = None
    type: str | None = None
    status: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class StorageDetails(BaseModel):
    uuid: str | None = None
    name: str | None = None
    mount_path: str | None = None
    is_directory: bool | None = None
    created_at: str | None = None
    updated_at: str | None = None


class StorageMetadata(StorageDetails):
    type: Literal["persistent", "file"]

    @classmethod
    def from_details(
        cls, details: StorageDetails, storage_type: Literal["persistent", "file"]
    ) -> Self:
        return cls(
            uuid=details.uuid,
            name=details.name,
            mount_path=details.mount_path,
            is_directory=details.is_directory,
            created_at=details.created_at,
            updated_at=details.updated_at,
            type=storage_type,
        )


class StorageInventory(BaseModel):
    persistent_storages: list[StorageDetails]
    file_storages: list[StorageDetails]


class EnvironmentMetadata(BaseModel):
    uuid: str | None = None
    key: str | None = None
    is_preview: bool | None = None
    is_runtime: bool | None = None
    is_buildtime: bool | None = None
    is_shared: bool | None = None
    is_shown_once: bool | None = None
    is_literal: bool | None = None
    is_multiline: bool | None = None
    version: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ServerList(RootModel[list[ServerMetadata]]):
    pass


class ServerResourceList(RootModel[list[ServerResourceMetadata]]):
    pass


class ApplicationList(RootModel[list[ApplicationMetadata]]):
    pass


class DeploymentList(RootModel[list[DeploymentMetadata]]):
    pass


class ApplicationStorages(BaseModel):
    application_uuid: str
    persistent_storages: list[StorageMetadata]
    file_storages: list[StorageMetadata]
    count: int
    contents_exposed: Literal[False] = False
    host_paths_exposed: Literal[False] = False


class ApplicationVariables(BaseModel):
    application_uuid: str
    variables: list[EnvironmentMetadata]
    count: int
    values_exposed: Literal[False] = False


class ApplicationDeployments(BaseModel):
    deployments: list[DeploymentMetadata]
    count: int


class CoolifyAccountSummary(AccountConnectionSummary):
    permission_contract: str


class EnvironmentList(RootModel[list[EnvironmentMetadata]]):
    pass


class DeploymentInventory(BaseModel):
    deployments: list[DeploymentMetadata]
