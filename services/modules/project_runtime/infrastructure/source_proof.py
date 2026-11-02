"""Compatibility exports for the shared project runtime client implementation."""

from uuid import UUID as UUID

from project_runtime_client.a11_owner_wire import A11OwnerCommandDTO as A11OwnerCommandDTO
from project_runtime_client.a11_owner_wire import (
    VerifiedA11SourceVersions as VerifiedA11SourceVersions,
)
from project_runtime_client.authorization import ProjectOwnerFence as ProjectOwnerFence
from project_runtime_client.authorization import ProjectPermit as ProjectPermit
from project_runtime_client.domain.source_proof import AuthorityEpochs as AuthorityEpochs
from project_runtime_client.domain.source_proof import AuthorityVersions as AuthorityVersions
from project_runtime_client.domain.source_proof import EffectSubject as EffectSubject
from project_runtime_client.domain.source_proof import ResourceVersions as ResourceVersions
from project_runtime_client.domain.source_proof import SourceProof as SourceProof
from project_runtime_client.domain.source_proof import SourceProofMismatch as SourceProofMismatch
from project_runtime_client.domain.source_proof import (
    SourceProofRequirement as SourceProofRequirement,
)
from project_runtime_client.infrastructure.source_proof import (
    dispatch_requirement as dispatch_requirement,
)
from project_runtime_client.infrastructure.source_proof import source_proof as source_proof
from project_runtime_client.infrastructure.source_proof import (
    status_requirement as status_requirement,
)
from project_runtime_client.owner_authorization import (
    VerifiedOwnerRecipient as VerifiedOwnerRecipient,
)
