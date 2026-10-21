from __future__ import annotations

from common.models import JsonObject

from .api import GitLabApiClient
from .errors import GitLabError


class GitLabMergeRequestClient(GitLabApiClient):
    def list_merge_requests(
        self,
        project: str | int,
        state: str = "opened",
        source_branch: str = "",
        target_branch: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/merge_requests",
            query={
                "state": state or None,
                "source_branch": source_branch or None,
                "target_branch": target_branch or None,
                "page": page,
                "per_page": per_page,
            },
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab merge request list response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "merge_requests": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def get_merge_request(self, project: str | int, iid: int) -> JsonObject:
        selector = self.project_selector(project)
        data = self.request(
            "GET",
            f"/projects/{selector}/merge_requests/{iid}",
            query={"include_diverged_commits_count": True, "include_rebase_in_progress": True},
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "merge_request": data,
        }

    def create_merge_request(
        self,
        project: str | int,
        source_branch: str,
        target_branch: str,
        title: str,
        delete_source_branch_after_merge: bool,
        description: str = "",
        squash: bool = False,
        draft: bool = False,
    ) -> JsonObject:
        if type(delete_source_branch_after_merge) is not bool:
            raise GitLabError("Explicit keep/delete source branch choice required")
        selector = self.project_selector(project)
        mr_title = title
        if draft and not title.lower().startswith(("draft:", "wip:")):
            mr_title = f"Draft: {title}"
        payload = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": mr_title,
            "description": description,
            "remove_source_branch": delete_source_branch_after_merge,
            "squash": squash,
        }
        data = self.request(
            "POST",
            f"/projects/{selector}/merge_requests",
            payload=payload,
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "merge_request": data,
        }

    def update_merge_request(
        self,
        project: str | int,
        iid: int,
        title: str | None = None,
        description: str | None = None,
        state_event: str | None = None,
        target_branch: str | None = None,
        delete_source_branch_after_merge: bool | None = None,
        squash: bool | None = None,
    ) -> JsonObject:
        selector = self.project_selector(project)
        payload: JsonObject = {}
        for key, value in {
            "title": title,
            "description": description,
            "state_event": state_event,
            "target_branch": target_branch,
            "remove_source_branch": delete_source_branch_after_merge,
            "squash": squash,
        }.items():
            if value is not None:
                payload[key] = value
        if not payload:
            raise GitLabError("at least one merge request field must be supplied")
        data = self.request(
            "PUT",
            f"/projects/{selector}/merge_requests/{iid}",
            payload=payload,
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "merge_request": data,
        }


    def list_merge_request_diffs(
        self,
        project: str | int,
        iid: int,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/merge_requests/{iid}/diffs",
            query={"page": page, "per_page": per_page},
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab merge request diff response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "iid": iid,
            "diffs": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def add_merge_request_note(
        self,
        project: str | int,
        iid: int,
        body: str,
    ) -> JsonObject:
        selector = self.project_selector(project)
        if not body.strip():
            raise GitLabError("merge request note body is required")
        data = self.request(
            "POST",
            f"/projects/{selector}/merge_requests/{iid}/notes",
            payload={"body": body},
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "iid": iid,
            "note": data,
        }

    def merge_merge_request(
        self,
        project: str | int,
        iid: int,
        delete_source_branch_after_merge: bool,
        sha: str = "",
        squash: bool | None = None,
        merge_when_pipeline_succeeds: bool = False,
        merge_commit_message: str = "",
        squash_commit_message: str = "",
    ) -> JsonObject:
        if type(delete_source_branch_after_merge) is not bool or not sha:
            raise GitLabError("Explicit keep/delete choice and expected source sha required")
        selector = self.project_selector(project)
        current = self.request("GET", f"/projects/{selector}/merge_requests/{iid}").data
        if not isinstance(current, dict) or current.get("sha") != sha:
            raise GitLabError("Merge request head changed")
        if current.get("source_project_id") != current.get("target_project_id"):
            raise GitLabError("Cross-project merge cleanup is disabled")
        source_branch = str(current.get("source_branch", ""))
        if delete_source_branch_after_merge:
            from .policy import require_mutable_branch
            require_mutable_branch(source_branch, self.protected_branches)
            branch = self.request("GET", f"/projects/{selector}/repository/branches/{self.project_selector(source_branch)}").data
            if not isinstance(branch, dict) or branch.get("protected") or branch.get("default") or source_branch == current.get("target_branch"):
                raise GitLabError("Cannot remove protected/default/target branch")
        elif current.get("force_remove_source_branch"):
            raise GitLabError("Project forced deletion conflicts with explicit keep choice")
        payload: JsonObject = {
            "merge_when_pipeline_succeeds": merge_when_pipeline_succeeds,
        }
        if sha:
            payload["sha"] = sha
        if squash is not None:
            payload["squash"] = squash
        payload["should_remove_source_branch"] = delete_source_branch_after_merge
        if merge_commit_message:
            payload["merge_commit_message"] = merge_commit_message
        if squash_commit_message:
            payload["squash_commit_message"] = squash_commit_message
        data = self.request(
            "PUT",
            f"/projects/{selector}/merge_requests/{iid}/merge",
            payload=payload,
        ).data
        cleanup = None
        merged = isinstance(data, dict) and data.get("state") == "merged"
        if merged and delete_source_branch_after_merge:
            cleaner = getattr(self, "_cleanup_merged_worktrees", None)
            if cleaner is not None:
                try:
                    cleanup = cleaner(str(project), source_branch, sha)
                except Exception:
                    cleanup = {"status": "cleanup_failed", "preserved": True}
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "merge_request": data,
            "source_branch_action": "delete" if delete_source_branch_after_merge else "keep",
            "local_cleanup": cleanup,
        }
