from __future__ import annotations

from typing import Literal
from urllib.parse import quote

from briareus_git.collaboration import (
    comment_payload,
    require_comment_deletion,
    validate_thread_page,
    validate_thread_target,
)
from briareus_json_values import JsonObject, StrictModel, json_object
from pydantic import Field, model_validator

from .api import GitLabApiClient
from .errors import GitLabError, GitLabRequestError
from .policy import require_mutable_branch


class DiffPosition(StrictModel):
    """GitLab native text diff coordinates pinned to a specific diff version."""

    base_sha: str = Field(min_length=1)
    start_sha: str = Field(min_length=1)
    head_sha: str = Field(min_length=1)
    old_path: str = Field(min_length=1)
    new_path: str = Field(min_length=1)
    old_line: int | None = Field(default=None, ge=1)
    new_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_line(self) -> DiffPosition:
        if self.old_line is None and self.new_line is None:
            raise ValueError("at least one diff line is required")
        return self


class GitLabReviewClient(GitLabApiClient):
    def _mr(self, project: str, iid: int) -> str:
        if iid < 1:
            raise GitLabRequestError("merge request iid must be positive")
        return f"/projects/{self.project_selector(project)}/merge_requests/{iid}"

    def _review_result(self, project: str, iid: int, key: str, data: object) -> JsonObject:
        return json_object(
            {"project": project, "iid": iid, key: data}, context="GitLab review result"
        )

    def get_merge_request_approvals(
        self, project: str, iid: int, include_rules: bool = False
    ) -> JsonObject:
        path = self._mr(project, iid)
        result = self._review_result(
            project, iid, "approvals", self.request("GET", path + "/approvals").data
        )
        if include_rules:
            result["approval_state"] = self.request("GET", path + "/approval_state").data
        return result

    def set_merge_request_approval(
        self, project: str, iid: int, approved: bool, expected_head_sha: str = ""
    ) -> JsonObject:
        if approved and not expected_head_sha.strip():
            raise GitLabRequestError("expected_head_sha is required to approve a merge request")
        if not approved and expected_head_sha:
            raise GitLabRequestError("GitLab unapprove does not support an expected head SHA")
        action = "approve" if approved else "unapprove"
        payload = {"sha": expected_head_sha} if approved else None
        data = self.request("POST", self._mr(project, iid) + "/" + action, payload=payload).data
        return self._review_result(project, iid, "approval", data)

    def list_review_threads(
        self, project: str, iid: int, per_page: int = 100, cursor: str | None = None
    ) -> JsonObject:
        validate_thread_page(iid, per_page, GitLabRequestError)
        if cursor is not None and (
            not cursor.isascii() or not cursor.isdecimal() or int(cursor) < 1
        ):
            raise GitLabRequestError("GitLab review cursor must be a positive page token")
        page = int(cursor) if cursor else 1
        response = self.request(
            "GET",
            self._mr(project, iid) + "/discussions",
            query={"page": page, "per_page": per_page},
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab discussions response")
        result = self._review_result(project, iid, "threads", response.data)
        result["next_cursor"] = response.headers.get("X-Next-Page") or None
        return result

    def create_review_thread(
        self, project: str, iid: int, body: str, position: DiffPosition | None = None
    ) -> JsonObject:
        path = self._mr(project, iid)
        payload = comment_payload(body, GitLabRequestError)
        if position is not None:
            mr = json_object(self.request("GET", path).data, context="GitLab merge request")
            refs = json_object(mr.get("diff_refs"), context="GitLab diff refs")
            expected = {
                key: getattr(position, key) for key in ("base_sha", "start_sha", "head_sha")
            }
            if any(refs.get(key) != value for key, value in expected.items()):
                raise GitLabRequestError("merge request diff version changed; refresh diff refs")
            payload["position"] = json_object(
                {**position.model_dump(exclude_none=True), "position_type": "text"},
                context="GitLab diff position",
            )
        return self._review_result(
            project,
            iid,
            "discussion",
            self.request("POST", path + "/discussions", payload=payload).data,
        )

    def reply_to_review_thread(
        self, project: str, iid: int, thread_id: str, body: str
    ) -> JsonObject:
        path = self._mr(project, iid) + f"/discussions/{quote(thread_id, safe='')}/notes"
        return self._review_result(
            project,
            iid,
            "note",
            self.request("POST", path, payload=comment_payload(body, GitLabRequestError)).data,
        )

    def update_review_comment(
        self, project: str, iid: int, thread_id: str, comment_id: int, body: str
    ) -> JsonObject:
        path = (
            self._mr(project, iid) + f"/discussions/{quote(thread_id, safe='')}/notes/{comment_id}"
        )
        return self._review_result(
            project,
            iid,
            "note",
            self.request("PUT", path, payload=comment_payload(body, GitLabRequestError)).data,
        )

    def set_review_thread_resolved(
        self, project: str, iid: int, thread_id: str, resolved: bool
    ) -> JsonObject:
        validate_thread_target(iid, thread_id, GitLabRequestError)
        path = self._mr(project, iid) + f"/discussions/{quote(thread_id, safe='')}"
        return self._review_result(
            project,
            iid,
            "discussion",
            self.request("PUT", path, payload={"resolved": resolved}).data,
        )

    def list_reviewers(self, project: str, iid: int) -> JsonObject:
        return self._review_result(
            project,
            iid,
            "reviewers",
            self.request("GET", self._mr(project, iid) + "/reviewers").data,
        )

    def set_reviewers(self, project: str, iid: int, reviewer_ids: list[int]) -> JsonObject:
        if any(value < 1 for value in reviewer_ids):
            raise GitLabRequestError("reviewer ids must be positive GitLab user IDs")
        return self._review_result(
            project,
            iid,
            "merge_request",
            self.request(
                "PUT", self._mr(project, iid), payload={"reviewer_ids": reviewer_ids}
            ).data,
        )

    def rebase_merge_request(self, project: str, iid: int, expected_head_sha: str) -> JsonObject:
        """GitLab queues a rebase; this precheck is not an atomic CAS."""
        path = self._mr(project, iid)
        mr = json_object(self.request("GET", path).data, context="GitLab merge request")
        if not expected_head_sha or mr.get("sha") != expected_head_sha:
            raise GitLabRequestError("merge request head changed or expected SHA is missing")
        if mr.get("source_project_id") != mr.get("target_project_id") or not mr.get(
            "source_project_id"
        ):
            raise GitLabRequestError("cross-project rebase is not supported")
        require_mutable_branch(str(mr.get("source_branch") or ""), self.protected_branches)
        response = self.request("PUT", path + "/rebase")
        return self._review_result(project, iid, "rebase", response.data)

    def add_note(
        self, project: str, target: Literal["issue", "merge_request"], iid: int, body: str
    ) -> JsonObject:
        data = self.request(
            "POST",
            self._notes_path(project, target, iid),
            payload=comment_payload(body, GitLabRequestError),
        ).data
        return self._review_result(project, iid, "note", data)

    def list_notes(
        self,
        project: str,
        target: Literal["issue", "merge_request"],
        iid: int,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        response = self.request(
            "GET",
            self._notes_path(project, target, iid),
            query={"page": page, "per_page": per_page},
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab notes response")
        result = self._review_result(project, iid, "notes", response.data)
        result["next_page"] = response.headers.get("X-Next-Page", "")
        return result

    def _notes_path(self, project: str, target: Literal["issue", "merge_request"], iid: int) -> str:
        if iid < 1:
            raise GitLabRequestError("iid must be positive")
        collection = {"issue": "issues", "merge_request": "merge_requests"}[target]
        return f"/projects/{self.project_selector(project)}/{collection}/{iid}/notes"

    def update_note(
        self,
        project: str,
        target: Literal["issue", "merge_request"],
        iid: int,
        note_id: int,
        body: str,
    ) -> JsonObject:
        path = self._notes_path(project, target, iid) + f"/{note_id}"
        return self._review_result(
            project,
            iid,
            "note",
            self.request("PUT", path, payload=comment_payload(body, GitLabRequestError)).data,
        )

    def delete_note(
        self,
        project: str,
        target: Literal["issue", "merge_request"],
        iid: int,
        note_id: int,
        confirm: bool = False,
    ) -> JsonObject:
        require_comment_deletion(note_id, confirm, GitLabRequestError)
        response = self.request("DELETE", self._notes_path(project, target, iid) + f"/{note_id}")
        return {
            "project": project,
            "iid": iid,
            "note_id": note_id,
            "deleted": True,
            "status": response.status,
        }

    def _review_graphql(
        self,
        project: str,
        iid: int,
        operation: Literal["mergeRequestRequestChanges", "mergeRequestSetDraft"],
        input_type: str,
        fields: JsonObject,
    ) -> JsonObject:
        project_data = json_object(
            self.request("GET", f"/projects/{self.project_selector(project)}").data,
            context="GitLab project",
        )
        full_path = project_data.get("path_with_namespace")
        if not isinstance(full_path, str) or not full_path:
            raise GitLabError("GitLab project has no path_with_namespace")
        variables = {"input": {"projectPath": full_path, "iid": str(iid), **fields}}
        query = (
            f"mutation Review($input: {input_type}!) {{ "
            f"{operation}(input: $input) {{ errors mergeRequest {{ iid title draft }} }} }}"
        )
        result = json_object(
            self.request(
                "POST", "/", graphql=True, payload={"query": query, "variables": variables}
            ).data,
            context="GitLab GraphQL response",
        )
        if result.get("errors"):
            raise GitLabError("GitLab GraphQL request failed; check provider rights and version")
        data = json_object(result.get("data"), context="GitLab GraphQL data")
        mutation = json_object(data.get(operation), context="GitLab GraphQL mutation")
        if mutation.get("errors") or not isinstance(mutation.get("mergeRequest"), dict):
            raise GitLabError("GitLab rejected the review mutation")
        return self._review_result(project, iid, "merge_request", mutation["mergeRequest"])

    def request_review_changes(self, project: str, iid: int, expected_head_sha: str) -> JsonObject:
        mr = json_object(
            self.request("GET", self._mr(project, iid)).data, context="GitLab merge request"
        )
        if not expected_head_sha or mr.get("sha") != expected_head_sha:
            raise GitLabRequestError("merge request head changed or expected SHA is missing")
        return self._review_graphql(
            project, iid, "mergeRequestRequestChanges", "MergeRequestRequestChangesInput", {}
        )

    def set_merge_request_draft(self, project: str, iid: int, draft: bool) -> JsonObject:
        self._mr(project, iid)
        return self._review_graphql(
            project, iid, "mergeRequestSetDraft", "MergeRequestSetDraftInput", {"draft": draft}
        )
