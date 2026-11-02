"""Admit every classified effect against the current provider policy."""

from dataclasses import dataclass
from typing import Literal

from svc_hand.domain.provider_policy import ProviderPolicy, SourceEffect


@dataclass(frozen=True)
class ToolEffects:
    provider: Literal["github", "gitlab"]
    effects: tuple[SourceEffect, ...]


@dataclass(frozen=True)
class AdmitSourceTool:
    github: ProviderPolicy
    gitlab: ProviderPolicy

    def execute(self, request: ToolEffects) -> None:
        policy = self.github if request.provider == "github" else self.gitlab
        for effect in request.effects:
            policy.require(effect)
