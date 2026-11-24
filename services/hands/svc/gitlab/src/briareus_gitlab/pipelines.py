from __future__ import annotations

from typing import Literal
from urllib.parse import quote

from briareus_git.ci import log_tail
from briareus_git.files import binary_result
from briareus_json_values import JsonObject

from .api import GitLabApiClient
from .errors import GitLabError


class GitLabPipelineClient(GitLabApiClient):
    def list_pipelines(
        self,
        project: str | int,
        ref: str = "",
        status: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/pipelines",
            query={
                "ref": ref or None,
                "status": status or None,
                "page": page,
                "per_page": per_page,
                "order_by": "id",
                "sort": "desc",
            },
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab pipeline list response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "pipelines": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def list_pipeline_jobs(
        self,
        project: str | int,
        pipeline_id: int,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/pipelines/{pipeline_id}/jobs",
            query={"page": page, "per_page": per_page},
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab pipeline jobs response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "pipeline_id": pipeline_id,
            "jobs": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def get_job_log(
        self,
        project: str | int,
        job_id: int,
        max_chars: int = 100_000,
    ) -> JsonObject:
        if max_chars <= 0 or max_chars > 2_000_000:
            raise GitLabError("max_chars must be between 1 and 2000000")
        selector = self.project_selector(project)
        response = self.request_text(
            "GET",
            f"/projects/{selector}/jobs/{job_id}/trace",
        )
        trace, truncated = log_tail(str(response.data), max_chars)
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "job_id": job_id,
            "truncated": truncated,
            "trace_tail": trace,
        }

    def retry_incomplete_run(self, project: str | int, pipeline_id: int) -> JsonObject:
        selector = self.project_selector(project)
        data = self.request(
            "POST",
            f"/projects/{selector}/pipelines/{pipeline_id}/retry",
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "pipeline": data,
        }

    def cancel_run(self, project: str | int, pipeline_id: int) -> JsonObject:
        selector = self.project_selector(project)
        data = self.request(
            "POST",
            f"/projects/{selector}/pipelines/{pipeline_id}/cancel",
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "pipeline": data,
        }

    def create_pipeline(
        self,
        project: str,
        ref: str,
        variables: dict[str, str] | None = None,
        inputs: JsonObject | None = None,
    ) -> JsonObject:
        selector = self.project_selector(project)
        payload: JsonObject = {"ref": ref}
        if variables is not None:
            payload["variables"] = [
                {"key": key, "value": value} for key, value in variables.items()
            ]
        if inputs is not None:
            payload["inputs"] = inputs
        data = self.request("POST", f"/projects/{selector}/pipeline", payload=payload).data
        return {"project": project, "pipeline": data}

    def get_pipeline(self, project: str, pipeline_id: int) -> JsonObject:
        selector = self.project_selector(project)
        data = self.request("GET", f"/projects/{selector}/pipelines/{pipeline_id}").data
        return {"project": project, "pipeline": data}

    def get_job(self, project: str, job_id: int) -> JsonObject:
        selector = self.project_selector(project)
        data = self.request("GET", f"/projects/{selector}/jobs/{job_id}").data
        return {"project": project, "job": data}

    def control_job(
        self, project: str, job_id: int, action: Literal["retry", "cancel", "play"]
    ) -> JsonObject:
        selector = self.project_selector(project)
        data = self.request("POST", f"/projects/{selector}/jobs/{job_id}/{action}").data
        return {"project": project, "job": data}

    def download_job_artifacts(
        self, project: str, job_id: int, path: str = "", max_bytes: int = 8 * 1024 * 1024
    ) -> JsonObject:
        selector = self.project_selector(project)
        endpoint = f"/projects/{selector}/jobs/{job_id}/artifacts"
        if path:
            parts = path.split("/")
            if any(part in {"", ".", ".."} for part in parts):
                raise GitLabError("artifact path must be a relative file path")
            endpoint += "/" + "/".join(quote(part, safe="") for part in parts)
        data = self.request_bytes(endpoint, max_bytes=max_bytes)
        return {"project": project, "job_id": job_id, "path": path, **binary_result(data)}

    def list_commit_statuses(
        self, project: str, sha: str, page: int = 1, per_page: int = 100
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/commits/{quote(sha, safe='')}/statuses",
            query={"page": page, "per_page": per_page},
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab commit statuses")
        return {
            "project": project,
            "sha": sha,
            "statuses": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }
