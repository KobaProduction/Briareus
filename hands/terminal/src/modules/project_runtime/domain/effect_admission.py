"""Compatibility exports for the shared project runtime client implementation."""

from dataclasses import dataclass as dataclass

from project_runtime_client.domain.authorization import ProjectAction as ProjectAction
from project_runtime_client.domain.authorization import ProjectInvocation as ProjectInvocation
from project_runtime_client.domain.authorization import (
    ProjectOperationScope as ProjectOperationScope,
)
from project_runtime_client.domain.effect_admission import EffectAdmission as EffectAdmission
from project_runtime_client.domain.effect_protocol import _PHASES as _PHASES
from project_runtime_client.domain.effect_protocol import EffectOwner as EffectOwner
from project_runtime_client.domain.effect_protocol import EffectPhase as EffectPhase
from project_runtime_client.domain.effect_receipt import (
    OwnerEffectUnavailable as OwnerEffectUnavailable,
)
from project_runtime_client.domain.revisions import valid_project_revision as valid_project_revision
