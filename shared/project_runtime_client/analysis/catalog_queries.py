"""Read the published SDK catalogue and return its existing concrete search/check views."""

from collections.abc import Sequence
from typing import Literal

from fastmcp.tools import Tool

from .catalog_views import (
    AnalysisToolAvailability,
    AnalysisToolCheck,
    AnalysisToolMatch,
    AnalysisToolSearch,
)


def search_catalog(public_tools: Sequence[Tool], query: str, limit: int) -> AnalysisToolSearch:
    tokens = [token.casefold() for token in query.split() if token.strip()]
    matches: list[AnalysisToolMatch] = []
    for tool in public_tools:
        haystack = " ".join(
            value for value in (tool.name, tool.title or "", tool.description or "") if value
        ).casefold()
        if tokens and not all(token in haystack for token in tokens):
            continue
        matches.append(AnalysisToolMatch(name=tool.name, description=tool.description or ""))
    matches.sort(key=lambda item: item.name)
    bounded_limit = max(1, min(limit, 100))
    return AnalysisToolSearch(
        query=query,
        match_count=len(matches),
        returned=min(len(matches), bounded_limit),
        matches=matches[:bounded_limit],
    )


def check_catalog(public_tools: Sequence[Tool], tools: str) -> AnalysisToolCheck:
    public_names = {tool.name for tool in public_tools}
    results: dict[str, AnalysisToolAvailability] = {}
    requested = [item.strip() for item in tools.split(",") if item.strip()]
    callable_count = 0
    for requested_name in requested:
        status: Literal["callable", "not_found"] = (
            "callable" if requested_name in public_names else "not_found"
        )
        if status == "callable":
            callable_count += 1
        results[requested_name] = AnalysisToolAvailability(status=status)
    return AnalysisToolCheck(results=results, summary=f"{callable_count}/{len(requested)} callable")
