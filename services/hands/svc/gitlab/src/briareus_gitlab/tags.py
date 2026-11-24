from __future__ import annotations

from urllib.parse import quote

from briareus_json_values import JsonObject, json_object

from .api import GitLabApiClient
from .errors import GitLabError


def _tag_summary(data: object) -> JsonObject:
    tag = json_object(data, context="GitLab tag")
    commit = json_object(tag.get("commit"), context="GitLab tag commit")
    name, sha = tag.get("name"), commit.get("id")
    if not isinstance(name, str) or not name or not isinstance(sha, str) or not sha:
        raise GitLabError("GitLab tag response lacks name or commit ID")
    return {"name": name, "sha": sha}


class GitLabTagClient(GitLabApiClient):
    def list_tags(self, repository: str, per_page: int = 100, page: int = 1) -> JsonObject:
        response = self.request(
            "GET",
            f"/projects/{self.project_selector(repository)}/repository/tags",
            query={"per_page": per_page, "page": page},
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab tag list")
        return {
            "repository": repository,
            "tags": [_tag_summary(tag) for tag in response.data],
            "page": page,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def create_tag(
        self, repository: str, tag: str, target_ref: str, message: str | None = None
    ) -> JsonObject:
        payload: JsonObject = {"tag_name": tag, "ref": target_ref}
        if message:
            payload["message"] = message
        result = self.request(
            "POST",
            f"/projects/{self.project_selector(repository)}/repository/tags",
            payload=payload,
        )
        summary = _tag_summary(result.data)
        if summary["name"] != tag:
            raise GitLabError("GitLab returned an unexpected tag name")
        return {
            "repository": repository,
            "tag": tag,
            "target_sha": summary["sha"],
            "annotated": bool(message),
        }

    def delete_tag(self, repository: str, tag: str) -> JsonObject:
        result = self.request(
            "DELETE",
            f"/projects/{self.project_selector(repository)}/repository/tags/{quote(tag, safe='')}",
        )
        return {"repository": repository, "tag": tag, "deleted": True, "status": result.status}
