"""Provider project schemas, independent of Briareus project persistence."""

from pydantic import BaseModel, Field, RootModel

from .pagination import PageQuery


class GitLabNamespace(BaseModel):
    id: int
    name: str
    path: str
    kind: str
    full_path: str
    parent_id: int | None = None
    avatar_url: str | None = None
    web_url: str | None = None


class ProjectMembership(BaseModel):
    access_level: int
    notification_level: int | None = None


class ProjectPermissions(BaseModel):
    project_access: ProjectMembership | None = None
    group_access: ProjectMembership | None = None


class GitLabProject(BaseModel):
    id: int
    name: str
    path: str
    path_with_namespace: str
    name_with_namespace: str | None = None
    description: str | None = None
    default_branch: str | None = None
    visibility: str
    web_url: str
    ssh_url_to_repo: str | None = None
    http_url_to_repo: str | None = None
    readme_url: str | None = None
    avatar_url: str | None = None
    created_at: str | None = None
    last_activity_at: str | None = None
    archived: bool = False
    empty_repo: bool = False
    namespace: GitLabNamespace | None = None
    permissions: ProjectPermissions | None = None
    topics: list[str] = Field(default_factory=list)
    tag_list: list[str] = Field(default_factory=list)
    star_count: int = 0
    forks_count: int = 0
    open_issues_count: int | None = None
    issues_enabled: bool | None = None
    merge_requests_enabled: bool | None = None
    jobs_enabled: bool | None = None
    wiki_enabled: bool | None = None
    snippets_enabled: bool | None = None
    container_registry_enabled: bool | None = None
    shared_runners_enabled: bool | None = None


class ProjectRecords(RootModel[list[GitLabProject]]):
    pass


class ProjectQuery(PageQuery):
    membership: bool
    owned: bool
    simple: bool = True
    order_by: str = "path"
    sort: str = "asc"
    search: str | None = None
    min_access_level: int | None = None
