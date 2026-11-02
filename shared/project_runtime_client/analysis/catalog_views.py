"""Public results of Analysis catalog queries."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class AnalysisToolMatch(BaseModel):
    name: str
    status: Literal["callable"] = "callable"
    description: str


class AnalysisToolSearch(BaseModel):
    query: str
    match_count: int
    returned: int
    matches: list[AnalysisToolMatch]


class AnalysisToolAvailability(BaseModel):
    status: Literal["callable", "not_found"]


class AnalysisToolCheck(BaseModel):
    results: dict[str, AnalysisToolAvailability]
    summary: str


class AnalysisVocabulary(BaseModel):
    """The fixed public terms published by this analysis service."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    action: str
    actions: str
    inbound_action: str
    outbound_action: str
    link: str
    link_map: str
    behavior: str
    low_level_view: str
    low_level_operation: str
    ir: str
    program: str
    project: str
    data_region: str
    data_link: str
    action_route: str
    annotation: str
    data_space: str
    forwarder: str
    behavior_annotation: str
    low_level_annotation: str
