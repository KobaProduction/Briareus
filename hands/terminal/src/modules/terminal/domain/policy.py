"""Compatibility API for the canonical typed Terminal technical client."""

from __future__ import annotations

import math as math
import re as re
from dataclasses import dataclass as dataclass

from project_runtime_client.terminal.domain.policy import EnvironmentVariable as EnvironmentVariable
from project_runtime_client.terminal.domain.policy import JobPage as JobPage
from project_runtime_client.terminal.domain.policy import JobRuntimeLimit as JobRuntimeLimit
from project_runtime_client.terminal.domain.policy import PositiveTimeout as PositiveTimeout
from project_runtime_client.terminal.domain.policy import RetentionPolicy as RetentionPolicy
from project_runtime_client.terminal.domain.policy import TerminalError as TerminalError
from project_runtime_client.terminal.domain.policy import TerminalSize as TerminalSize
from project_runtime_client.terminal.domain.policy import WorkspaceIdentity as WorkspaceIdentity
