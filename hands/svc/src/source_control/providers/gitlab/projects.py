from __future__ import annotations

from .api import GitLabApiClient
from .errors import GitLabError
from .infrastructure.schemas.identity import (
    AuthenticatedGitLabUser,
    GitLabVersion,
    PersonalAccessToken,
)
from .infrastructure.schemas.projects import (
    GitLabProject,
    ProjectMembership,
    ProjectQuery,
    ProjectRecords,
)
from .project_views import (
    GitLabAccountCapabilities,
    GitLabProfileStatus,
    GitLabProjectList,
    GitLabProjectStatus,
    ProjectAccess,
    ProjectAccesses,
    ProjectScope,
    PublicPermissions,
    TokenPermissions,
    UnknownPermissions,
)


class GitLabProjectClient(GitLabApiClient):
    def profile_status(self) -> GitLabProfileStatus:
        version = self.inspect_model(
            "/version", response_type=GitLabVersion, unavailable_statuses={401, 403, 404}
        )
        if self.anonymous_only:
            return GitLabProfileStatus(
                account=self.profile.public().model_copy(update={"auth_type": "public"}),
                authenticated_user=None,
                gitlab_version=version,
                status="ok",
                access_mode="public_anonymous",
            )
        user = self.request_model("GET", "/user", response_type=AuthenticatedGitLabUser).data
        return GitLabProfileStatus(
            account=self.profile.public(),
            authenticated_user=user,
            gitlab_version=version,
            status="ok",
        )

    def account_capabilities(self, project: str = "") -> GitLabAccountCapabilities:
        """Return provider-visible account scope and optional project access details."""
        if self.anonymous_only:
            public_result = GitLabAccountCapabilities(
                account=self.profile.public().model_copy(update={"auth_type": "public"}),
                auth_type="public",
                provider_permissions_known=True,
                provider_permissions=PublicPermissions(repository="read"),
                note="Anonymous public GitLab access; read-only.",
            )
            if project:
                project_result = self.project_status(project).project
                public_result.project = ProjectScope(
                    selector=project,
                    id=project_result.id,
                    path_with_namespace=project_result.path_with_namespace,
                    visibility=project_result.visibility,
                    access=ProjectAccesses(),
                )
            return public_result

        result = GitLabAccountCapabilities(
            account=self.profile.public(),
            auth_type=self.profile.auth_type,
            provider_permissions_known=False,
            provider_permissions=UnknownPermissions(),
        )

        if self.profile.auth_type == "private_token":
            token = self.inspect_model(
                "/personal_access_tokens/self",
                response_type=PersonalAccessToken,
                unavailable_statuses={401, 403, 404},
            )
            if token is not None:
                result.provider_permissions_known = token.scopes is not None
                result.provider_permissions = TokenPermissions(
                    scopes=token.scopes or [], active=token.active, expires_at=token.expires_at
                )
            else:
                result.note = (
                    "GitLab did not expose PAT self-inspection for this server/token; "
                    "effective rights remain project/resource dependent."
                )
        else:
            result.note = (
                "This GitLab auth type has no reliable account-global permission map; "
                "effective rights are project/resource dependent."
            )

        if project:
            project_result = self.project_status(project).project
            permissions = project_result.permissions
            access = ProjectAccesses(
                project_access=_project_access(permissions.project_access) if permissions else None,
                group_access=_project_access(permissions.group_access) if permissions else None,
            )
            result.project = ProjectScope(
                selector=project,
                id=project_result.id,
                path_with_namespace=project_result.path_with_namespace,
                visibility=project_result.visibility,
                access=access,
            )
        return result

    def list_projects(
        self,
        search: str = "",
        membership: bool = True,
        owned: bool = False,
        min_access_level: int = 0,
        page: int = 1,
        per_page: int = 100,
    ) -> GitLabProjectList:
        if page <= 0 or per_page <= 0 or per_page > 100:
            raise GitLabError("page must be > 0 and per_page must be between 1 and 100")
        query = ProjectQuery(
            membership=membership,
            owned=owned,
            page=page,
            per_page=per_page,
            search=search.strip() or None,
            min_access_level=min_access_level or None,
        )
        response = self.request_model("GET", "/projects", query=query, response_type=ProjectRecords)
        return GitLabProjectList(
            account_id=self.profile.account_id,
            projects=response.data.root,
            page=page,
            per_page=per_page,
            next_page=response.pagination.next_page,
            total=response.pagination.total,
            total_pages=response.pagination.total_pages,
        )

    def project_status(self, project: str | int) -> GitLabProjectStatus:
        selector = self.project_selector(project)
        data = self.request_model("GET", f"/projects/{selector}", response_type=GitLabProject).data
        return GitLabProjectStatus(account_id=self.profile.account_id, project=data)


def _access_level_name(value: int) -> str:
    levels = {
        0: "no_access",
        5: "minimal_access",
        10: "guest",
        15: "planner",
        20: "reporter",
        30: "developer",
        40: "maintainer",
        50: "owner",
    }
    return levels.get(value, "unknown")


def _project_access(membership: ProjectMembership | None) -> ProjectAccess | None:
    if membership is None:
        return None
    return ProjectAccess(
        access_level=membership.access_level,
        access_level_name=_access_level_name(membership.access_level),
    )
