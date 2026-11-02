"""Compatibility exports for the shared GitLab technical implementation."""

from dataclasses import dataclass as dataclass
from typing import Literal as Literal

from source_control.providers.gitlab.domain.mutations import CommitAction as CommitAction
from source_control.providers.gitlab.domain.mutations import CommitEdit as CommitEdit
from source_control.providers.gitlab.domain.mutations import (
    MergeRequestUpdate as MergeRequestUpdate,
)
from source_control.providers.gitlab.domain.mutations import (
    merge_request_title as merge_request_title,
)
from source_control.providers.gitlab.domain.mutations import require_note_body as require_note_body

from .errors import GitLabError as GitLabError
