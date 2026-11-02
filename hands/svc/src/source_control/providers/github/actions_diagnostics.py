from __future__ import annotations

import base64
import hashlib
import urllib.error
import urllib.parse
import urllib.request

from .base import GitHubRepositoryClientBase
from .execution_views import (
    WorkflowArtifact,
    WorkflowFileDownload,
    WorkflowFileList,
    WorkflowJobLog,
)
from .github_agent import GitHubAgentError
from .infrastructure.schemas.actions import WorkflowArtifacts
from .infrastructure.schemas.pagination import PageQuery

_GITHUB_API = "https://api.github.com"
_MAX_LOG_BYTES = 8 * 1024 * 1024
_MAX_WORKFLOW_FILE_BYTES = 8 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        del req, fp, code, msg, headers, newurl
        return None


class GitHubActionsDiagnosticsClient(GitHubRepositoryClientBase):
    def _download_redirect_bytes(
        self,
        repository: str,
        endpoint: str,
        max_bytes: int,
    ) -> bytes:
        repository = self._assert_allowed(repository)
        max_bytes = max(1, min(max_bytes, 16 * 1024 * 1024))
        token = self._installation_token(repository)
        request = urllib.request.Request(  # noqa: S310 -- URL starts with the fixed GitHub HTTPS origin
            f"{_GITHUB_API}{endpoint}",
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "mcp-bridge",
                "X-GitHub-Api-Version": "2026-03-10",
            },
        )
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            response = opener.open(request, timeout=30)
        except urllib.error.HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                detail = exc.read(4096).decode("utf-8", "replace")
                raise GitHubAgentError(
                    f"GitHub download endpoint returned HTTP {exc.code}: {detail}"
                ) from exc
            location = exc.headers.get("Location", "")
            if not location:
                raise GitHubAgentError("GitHub download redirect has no Location header") from exc
            parsed = urllib.parse.urlparse(location)
            if parsed.scheme != "https" or not parsed.netloc:
                raise GitHubAgentError("GitHub download redirect is not a valid HTTPS URL") from exc
            redirected = urllib.request.Request(  # noqa: S310 -- redirect scheme/authority checked above
                location,
                method="GET",
                headers={"User-Agent": "mcp-bridge"},
            )
            try:
                response = urllib.request.urlopen(redirected, timeout=60)  # noqa: S310 -- verified HTTPS redirect
            except urllib.error.URLError as redirect_exc:
                raise GitHubAgentError(
                    f"GitHub redirected download failed: {redirect_exc.reason}"
                ) from redirect_exc
        except urllib.error.URLError as exc:
            raise GitHubAgentError(f"GitHub download transport error: {exc.reason}") from exc

        with response:
            data = bytes(response.read(max_bytes + 1))
        if len(data) > max_bytes:
            raise GitHubAgentError(f"download exceeds MCP safety limit of {max_bytes} bytes")
        return data

    def get_workflow_job_log(
        self,
        repository: str,
        job_id: int,
        max_chars: int = 100_000,
    ) -> WorkflowJobLog:
        repository = self._assert_allowed(repository)
        max_chars = max(1, min(max_chars, 500_000))
        data = self._download_redirect_bytes(
            repository,
            f"/repos/{repository}/actions/jobs/{job_id}/logs",
            _MAX_LOG_BYTES,
        )
        text = data.decode("utf-8", "replace")
        truncated = len(text) > max_chars
        if truncated:
            text = text[-max_chars:]
        return WorkflowJobLog(
            repository=repository,
            job_id=job_id,
            log=text,
            tail_chars=max_chars,
            truncated=truncated,
            downloaded_bytes=len(data),
        )

    def list_workflow_files(
        self,
        repository: str,
        run_id: int,
        per_page: int = 100,
        page: int = 1,
    ) -> WorkflowFileList:
        repository = self._assert_allowed(repository)
        result = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/actions/runs/{run_id}/artifacts",
            response_type=WorkflowArtifacts,
            query=PageQuery(per_page=max(1, min(per_page, 100)), page=max(1, page)),
        ).data
        files = [
            WorkflowArtifact(
                id=item.id,
                name=item.name,
                size_in_bytes=item.size_in_bytes,
                expired=item.expired,
                created_at=item.created_at or "",
                expires_at=item.expires_at or "",
            )
            for item in result.artifacts
        ]
        return WorkflowFileList(
            repository=repository,
            run_id=run_id,
            total_count=result.total_count if result.total_count is not None else len(files),
            files=files,
            page=page,
        )

    def download_workflow_file(
        self,
        repository: str,
        workflow_file_id: int,
        max_bytes: int = _MAX_WORKFLOW_FILE_BYTES,
    ) -> WorkflowFileDownload:
        repository = self._assert_allowed(repository)
        data = self._download_redirect_bytes(
            repository,
            f"/repos/{repository}/actions/artifacts/{workflow_file_id}/zip",
            max_bytes,
        )
        return WorkflowFileDownload(
            repository=repository,
            workflow_file_id=workflow_file_id,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            content_base64=base64.b64encode(data).decode("ascii"),
        )
