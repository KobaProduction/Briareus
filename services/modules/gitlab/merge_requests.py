"""Public GitLab merge-request client entry point."""

from .infrastructure.merge_requests import GitLabMergeRequestClient as GitLabMergeRequestClient

__all__ = ["GitLabMergeRequestClient"]
