from __future__ import annotations

from .activity_views import (
    JobTrace,
    PipelineJobs,
    PipelineList,
    PipelineResult,
)
from .api import GitLabApiClient
from .errors import GitLabError
from .infrastructure.schemas.activity import (
    PipelineJobQuery,
    PipelineJobRecords,
    PipelineQuery,
    PipelineRecords,
)
from .infrastructure.schemas.pipelines import PipelineDetails


class GitLabPipelineClient(GitLabApiClient):
    def list_pipelines(
        self,
        project: str | int,
        ref: str = "",
        status: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> PipelineList:
        selector = self.project_selector(project)
        response = self.request_model(
            "GET",
            f"/projects/{selector}/pipelines",
            response_type=PipelineRecords,
            query=PipelineQuery(
                ref=ref or None, status=status or None, page=page, per_page=per_page
            ),
        )
        return PipelineList(
            profile_id=self.profile.profile_id,
            project=str(project),
            pipelines=response.data.root,
            next_page=response.pagination.next_page,
        )

    def list_pipeline_jobs(
        self,
        project: str | int,
        pipeline_id: int,
        page: int = 1,
        per_page: int = 100,
    ) -> PipelineJobs:
        selector = self.project_selector(project)
        response = self.request_model(
            "GET",
            f"/projects/{selector}/pipelines/{pipeline_id}/jobs",
            response_type=PipelineJobRecords,
            query=PipelineJobQuery(page=page, per_page=per_page),
        )
        return PipelineJobs(
            profile_id=self.profile.profile_id,
            project=str(project),
            pipeline_id=pipeline_id,
            jobs=response.data.root,
            next_page=response.pagination.next_page,
        )

    def job_trace(
        self,
        project: str | int,
        job_id: int,
        max_chars: int = 100_000,
    ) -> JobTrace:
        if max_chars <= 0 or max_chars > 2_000_000:
            raise GitLabError("max_chars must be between 1 and 2000000")
        selector = self.project_selector(project)
        response = self.request_text(
            "GET",
            f"/projects/{selector}/jobs/{job_id}/trace",
        )
        trace = str(response.data)
        return JobTrace(
            profile_id=self.profile.profile_id,
            project=str(project),
            job_id=job_id,
            truncated=len(trace) > max_chars,
            trace_tail=trace[-max_chars:],
        )

    def retry_pipeline(self, project: str | int, pipeline_id: int) -> PipelineResult:
        selector = self.project_selector(project)
        data = self.request_model(
            "POST",
            f"/projects/{selector}/pipelines/{pipeline_id}/retry",
            response_type=PipelineDetails,
        ).data
        return PipelineResult(
            profile_id=self.profile.profile_id, project=str(project), pipeline=data
        )

    def cancel_pipeline(self, project: str | int, pipeline_id: int) -> PipelineResult:
        selector = self.project_selector(project)
        data = self.request_model(
            "POST",
            f"/projects/{selector}/pipelines/{pipeline_id}/cancel",
            response_type=PipelineDetails,
        ).data
        return PipelineResult(
            profile_id=self.profile.profile_id, project=str(project), pipeline=data
        )
