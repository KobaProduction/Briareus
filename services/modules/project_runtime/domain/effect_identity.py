"""Compatibility exports for the shared project runtime client implementation."""

from dataclasses import dataclass as dataclass
from uuid import UUID as UUID

from project_runtime_client.domain.effect_identity import (
    EmbeddedEffectIdentity as EmbeddedEffectIdentity,
)
from project_runtime_client.domain.effect_identity import (
    OriginalEffectIdentity as OriginalEffectIdentity,
)
from project_runtime_client.domain.effect_receipt import (
    OwnerEffectUnavailable as OwnerEffectUnavailable,
)
from project_runtime_client.domain.identifiers import valid_uuid as valid_uuid
