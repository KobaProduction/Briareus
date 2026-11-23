from __future__ import annotations

import re
import urllib.parse

from briareus_json_values import JsonObject, json_member_object

from .api import GitLabApiClient
from .errors import GitLabError


class GitLabProjectClient(GitLabApiClient):
    def profile_status(self) -> JsonObject:
        if self.anonymous_only:
            version = self.request(
                "GET",
                "/version",
                allowed_errors={401, 403, 404},
            ).data
            account = self.profile.public()
            account["auth_type"] = "public"
            return {
                "account": account,
                "authenticated_user": None,
                "gitlab_version": version if isinstance(version, dict) else {},
                "status": "ok",
                "access_mode": "public_anonymous",
            }
        user = self.request("GET", "/user").data
        version = self.request("GET", "/version", allowed_errors={401, 403, 404}).data
        if not isinstance(user, dict):
            raise GitLabError("unexpected GitLab /user response")
        return {
            "account": self.profile.public(),
            "authenticated_user": {
                "id": user.get("id"),
                "username": user.get("username"),
                "name": user.get("name"),
                "state": user.get("state"),
                "web_url": user.get("web_url"),
            },
            "gitlab_version": version if isinstance(version, dict) else {},
            "status": "ok",
        }

    def account_capabilities(self, project: str = "") -> JsonObject:
        """Return provider-visible account scope and optional project access details."""
        if self.anonymous_only:
            public_result: JsonObject = {
                "account": {
                    **self.profile.public(),
                    "auth_type": "public",
                },
                "auth_type": "public",
                "provider_permissions_known": True,
                "provider_permissions": {"repository": "read"},
                "note": "Anonymous public GitLab access; read-only.",
            }
            if project:
                project_result = json_member_object(
                    self.project_status(project),
                    "project",
                    required=True,
                )
                public_result["project"] = {
                    "selector": project,
                    "id": project_result.get("id"),
                    "path_with_namespace": project_result.get("path_with_namespace"),
                    "visibility": project_result.get("visibility"),
                    "access": {},
                }
            return public_result

        result: JsonObject = {
            "account": self.profile.public(),
            "auth_type": self.profile.auth_type,
            "provider_permissions_known": False,
            "provider_permissions": {},
        }

        if self.profile.auth_type == "private_token":
            token_response = self.request(
                "GET",
                "/personal_access_tokens/self",
                allowed_errors={401, 403, 404},
            )
            if token_response.status < 400 and isinstance(token_response.data, dict):
                scopes = token_response.data.get("scopes")
                result["provider_permissions_known"] = isinstance(scopes, list)
                result["provider_permissions"] = {
                    "scopes": scopes if isinstance(scopes, list) else [],
                    "active": token_response.data.get("active"),
                    "expires_at": token_response.data.get("expires_at"),
                }
            else:
                result["note"] = (
                    "GitLab did not expose PAT self-inspection for this server/token; "
                    "effective rights remain project/resource dependent."
                )
        else:
            result["note"] = (
                "This GitLab auth type has no reliable account-global permission map; "
                "effective rights are project/resource dependent."
            )

        if project:
            result["project"] = self._project_access_capabilities(project)
        return result

    def _project_access_capabilities(self, project: str) -> JsonObject:
        project_result = json_member_object(
            self.project_status(project),
            "project",
            required=True,
        )
        permissions = project_result.get("permissions")
        access: JsonObject = {}
        if isinstance(permissions, dict):
            for source in ("project_access", "group_access"):
                raw = permissions.get(source)
                if isinstance(raw, dict):
                    level = raw.get("access_level")
                    access[source] = {
                        "access_level": level,
                        "access_level_name": _access_level_name(level),
                    }
        return {
            "selector": project,
            "id": project_result.get("id"),
            "path_with_namespace": project_result.get("path_with_namespace"),
            "visibility": project_result.get("visibility"),
            "access": access,
        }

    def _creation_namespace_id(self, namespace: str) -> int:
        target = self.request("GET", f"/namespaces/{urllib.parse.quote(namespace, safe='')}").data
        if (
            not isinstance(target, dict)
            or str(target.get("full_path", "")).casefold() != namespace.casefold()
        ):
            raise GitLabError("GitLab namespace did not match selected namespace")
        namespace_id = target.get("id")
        if type(namespace_id) is not int or namespace_id <= 0:
            raise GitLabError("GitLab namespace did not return a valid id")
        return namespace_id

    def _created_project_result(
        self, status: int, created: object, path: str, namespace: str, visibility: str
    ) -> JsonObject:
        if not isinstance(created, dict):
            raise GitLabError("GitLab project creation response is not an object")
        expected_full_path = f"{namespace}/{path}" if namespace else ""
        returned_full_path = str(created.get("path_with_namespace", ""))
        if (
            status != 201
            or str(created.get("path", "")).casefold() != path.casefold()
            or created.get("visibility") != visibility
            or (
                expected_full_path
                and returned_full_path.casefold() != expected_full_path.casefold()
            )
        ):
            raise GitLabError(
                "GitLab creation response did not match requested project/visibility; "
                "inspect the remote project before retrying"
            )
        return {
            "created": True,
            "account_id": self.profile.account_id,
            "id": created.get("id"),
            "path_with_namespace": returned_full_path,
            "url": created.get("web_url"),
            "visibility": created["visibility"],
            "default_branch": created.get("default_branch"),
        }

    def create_project(
        self,
        name: str,
        *,
        path: str = "",
        namespace: str = "",
        visibility: str = "private",
        description: str = "",
        initialize_with_readme: bool = False,
    ) -> JsonObject:
        """Create a GitLab project under the current user or an explicit namespace."""
        name = name.strip()
        path = (path or name).strip()
        namespace = namespace.strip().strip("/")
        if not name or len(name) > 255:
            raise GitLabError("project name must contain between 1 and 255 characters")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", path) or path.endswith((".", "-")):
            raise GitLabError("path must be a GitLab project slug without slashes")
        if visibility not in {"private", "internal", "public"}:
            raise GitLabError("visibility must be private, internal, or public")
        if self.anonymous_only or self.profile.auth_type == "job_token":
            raise GitLabError("project creation requires an authorized GitLab user token")

        payload: JsonObject = {
            "name": name,
            "path": path,
            "visibility": visibility,
            "description": description,
            "initialize_with_readme": initialize_with_readme,
        }
        if namespace:
            payload["namespace_id"] = self._creation_namespace_id(namespace)
        response = self.request("POST", "/projects", payload=payload)
        return self._created_project_result(
            response.status, response.data, path, namespace, visibility
        )

    def list_projects(
        self,
        search: str = "",
        membership: bool = True,
        owned: bool = False,
        min_access_level: int = 0,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        if page <= 0 or per_page <= 0 or per_page > 100:
            raise GitLabError("page must be > 0 and per_page must be between 1 and 100")
        query: JsonObject = {
            "membership": membership,
            "owned": owned,
            "simple": True,
            "page": page,
            "per_page": per_page,
            "order_by": "path",
            "sort": "asc",
        }
        if search.strip():
            query["search"] = search.strip()
        if min_access_level:
            query["min_access_level"] = min_access_level
        response = self.request("GET", "/projects", query=query)
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab project list response")
        return {
            "account_id": self.profile.account_id,
            "projects": response.data,
            "page": page,
            "per_page": per_page,
            "next_page": response.headers.get("X-Next-Page", ""),
            "total": _header_int(response.headers, "X-Total"),
            "total_pages": _header_int(response.headers, "X-Total-Pages"),
        }

    def project_status(self, project: str | int) -> JsonObject:
        selector = self.project_selector(project)
        data = self.request("GET", f"/projects/{selector}").data
        if not isinstance(data, dict):
            raise GitLabError("unexpected GitLab project response")
        return {"account_id": self.profile.account_id, "project": data}


def _header_int(headers: dict[str, str], name: str) -> int | None:
    raw = headers.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _access_level_name(value: object) -> str:
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
    return levels.get(value, "unknown") if isinstance(value, int) else "unknown"
