"""Compatibility exports for the shared Analysis client implementation."""

from __future__ import annotations

from collections.abc import Sequence as Sequence
from typing import Literal as Literal

from fastmcp.tools import Tool as Tool

from project_runtime_client.analysis.catalog_queries import check_catalog as check_catalog
from project_runtime_client.analysis.catalog_queries import search_catalog as search_catalog

from .catalog_views import AnalysisToolAvailability as AnalysisToolAvailability
from .catalog_views import AnalysisToolCheck as AnalysisToolCheck
from .catalog_views import AnalysisToolMatch as AnalysisToolMatch
from .catalog_views import AnalysisToolSearch as AnalysisToolSearch
