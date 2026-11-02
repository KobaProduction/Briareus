"""Compatibility exports for the shared project runtime client implementation."""

from datetime import UTC as UTC
from datetime import datetime as datetime
from typing import Literal as Literal
from typing import Protocol as Protocol
from uuid import UUID as UUID

from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pydantic import Field as Field
from pydantic import field_validator as field_validator
from pydantic import model_validator as model_validator

from project_runtime_client.a11_owner_wire import A11OwnerCommandDTO as A11OwnerCommandDTO
from project_runtime_client.a11_owner_wire import A11TargetOwner as A11TargetOwner
from project_runtime_client.a11_owner_wire import VerifiedA11RevisionPort as VerifiedA11RevisionPort
from project_runtime_client.a11_owner_wire import (
    VerifiedA11SourceVersions as VerifiedA11SourceVersions,
)
from project_runtime_client.authorization import ProjectInvocation as ProjectInvocation
from project_runtime_client.authorization import ProjectPermit as ProjectPermit
from project_runtime_client.domain.identifiers import valid_uuid as valid_uuid
from project_runtime_client.owner_authorization import (
    VerifiedOwnerRecipient as VerifiedOwnerRecipient,
)
