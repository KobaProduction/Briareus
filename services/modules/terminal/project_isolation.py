"""Compatibility API for the canonical typed Terminal technical client."""

from __future__ import annotations

import asyncio as asyncio
import math as math
from dataclasses import dataclass as dataclass
from datetime import UTC as UTC
from datetime import datetime as datetime
from typing import Protocol as Protocol
from uuid import UUID as UUID

from modules.project_runtime import ProjectInvocation as ProjectInvocation
from modules.project_runtime import ProjectPermit as ProjectPermit
from modules.project_runtime import ProjectRuntimeAuthority as ProjectRuntimeAuthority
from project_runtime_client.terminal.project_isolation import (
    ProjectIsolationAttestation as ProjectIsolationAttestation,
)
from project_runtime_client.terminal.project_isolation import (
    ProjectIsolationInspector as ProjectIsolationInspector,
)
from project_runtime_client.terminal.project_isolation import (
    ProjectIsolationSupervisorPort as ProjectIsolationSupervisorPort,
)
from project_runtime_client.terminal.project_isolation import (
    ProjectIsolationUnavailable as ProjectIsolationUnavailable,
)
