"""Only a current, versioned Project permit can name an owned workspace."""

from datetime import datetime
from uuid import UUID

from project_runtime_client.domain._code_error import _CodeError

from .authorization import ProjectPermit
from .timestamps import aware_timestamp


class ProjectFileError(_CodeError):
    pass


def project_directory_name(permit: ProjectPermit, *, now: datetime) -> str:
    if not isinstance(permit, ProjectPermit):
        raise ProjectFileError("PROJECT_ID_INVALID")
    if not isinstance(permit.project_id, UUID):
        raise ProjectFileError("PROJECT_ID_INVALID")
    if (
        not aware_timestamp(permit.expires_at)
        or permit.expires_at.tzinfo is None
        or permit.expires_at <= now
        or type(permit.decision_version) is not int
        or permit.decision_version < 1
    ):
        raise ProjectFileError("PROJECT_PERMIT_EXPIRED")
    return str(permit.project_id)
