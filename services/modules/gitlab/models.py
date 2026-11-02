"""Compatibility exports for the shared GitLab technical implementation."""

from typing import Literal as Literal

from pydantic import Field as Field
from pydantic import PrivateAttr as PrivateAttr
from pydantic import field_validator as field_validator
from pydantic import model_validator as model_validator

from common.models import StrictModel as StrictModel
from source_control.providers.gitlab.models import GitLabCommitAction as GitLabCommitAction
from source_control.providers.gitlab.models import GitLabProfile as GitLabProfile

from .domain.mutations import CommitAction as CommitAction
from .domain.mutations import CommitEdit as CommitEdit
from .project_views import PublicGitLabProfile as PublicGitLabProfile
