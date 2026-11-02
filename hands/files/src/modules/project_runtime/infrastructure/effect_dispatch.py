"""Owner-local compatibility and codec boundary for shared runtime clients."""

from __future__ import annotations

import asyncio as asyncio
from dataclasses import dataclass as dataclass
from typing import TYPE_CHECKING as TYPE_CHECKING

from pydantic import BaseModel as BaseModel

from modules.project_runtime.domain.effect_receipt import (
    OwnerEffectUnavailable as OwnerEffectUnavailable,
)
from project_runtime_client.infrastructure.effect_dispatch import EffectDispatch as EffectDispatch
from project_runtime_client.infrastructure.effect_dispatch import dispatch_effect as dispatch_effect
