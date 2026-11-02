"""Compatibility exports for the shared project runtime client implementation."""

from dataclasses import dataclass as dataclass
from datetime import datetime as datetime
from uuid import UUID as UUID

from project_runtime_client.domain.source_proof import AuthorityEpochs as AuthorityEpochs
from project_runtime_client.domain.source_proof import AuthorityVersions as AuthorityVersions
from project_runtime_client.domain.source_proof import EffectSubject as EffectSubject
from project_runtime_client.domain.source_proof import ResourceVersions as ResourceVersions
from project_runtime_client.domain.source_proof import SourceProof as SourceProof
from project_runtime_client.domain.source_proof import SourceProofMismatch as SourceProofMismatch
from project_runtime_client.domain.source_proof import (
    SourceProofRequirement as SourceProofRequirement,
)
