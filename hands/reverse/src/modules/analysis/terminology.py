"""Compatibility exports for the shared Analysis client implementation."""

from __future__ import annotations

import re as re

from common.public_tool_names import analysis_public_tool_name as analysis_public_tool_name
from project_runtime_client.analysis.terminology import _ARGUMENT_ALIASES as _ARGUMENT_ALIASES
from project_runtime_client.analysis.terminology import _ARGUMENT_TOKENS as _ARGUMENT_TOKENS
from project_runtime_client.analysis.terminology import (
    _COLLAPSED_ACTION_SELECTOR_TOOLS as _COLLAPSED_ACTION_SELECTOR_TOOLS,
)
from project_runtime_client.analysis.terminology import (
    _FORBIDDEN_ANALYSIS_TERMS as _FORBIDDEN_ANALYSIS_TERMS,
)
from project_runtime_client.analysis.terminology import _GROUP_ALIASES as _GROUP_ALIASES
from project_runtime_client.analysis.terminology import _RESULT_KEY_ALIASES as _RESULT_KEY_ALIASES
from project_runtime_client.analysis.terminology import (
    _RESULT_METADATA_KEYS as _RESULT_METADATA_KEYS,
)
from project_runtime_client.analysis.terminology import _RESULT_OPAQUE_KEYS as _RESULT_OPAQUE_KEYS
from project_runtime_client.analysis.terminology import _TEXT_TERMS as _TEXT_TERMS
from project_runtime_client.analysis.terminology import (
    _TOOL_ARGUMENT_ALIASES as _TOOL_ARGUMENT_ALIASES,
)
from project_runtime_client.analysis.terminology import _TOOL_TOKENS as _TOOL_TOKENS
from project_runtime_client.analysis.terminology import ANALYSIS_VOCABULARY as ANALYSIS_VOCABULARY
from project_runtime_client.analysis.terminology import (
    analysis_argument_name as analysis_argument_name,
)
from project_runtime_client.analysis.terminology import analysis_group_name as analysis_group_name
from project_runtime_client.analysis.terminology import analysis_result_key as analysis_result_key
from project_runtime_client.analysis.terminology import analysis_result_text as analysis_result_text
from project_runtime_client.analysis.terminology import (
    analysis_surface_violations as analysis_surface_violations,
)
from project_runtime_client.analysis.terminology import analysis_text as analysis_text
from project_runtime_client.analysis.terminology import analysis_tool_name as analysis_tool_name
from project_runtime_client.analysis.terminology import analysis_vocabulary as analysis_vocabulary

from .catalog_views import AnalysisVocabulary as AnalysisVocabulary
