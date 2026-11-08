from briareus_json_values import ProviderModel, StrictModel
from pydantic import Field


class AnalysisProject(ProviderModel):
    """Known panel fields; extension fields belong to the external analysis provider."""

    project_id: str
    name: str = ""
    path: str = ""
    session: str = ""
    worker_index: int | None = None
    group: str = ""


class AnalysisWorker(ProviderModel):
    worker_index: int
    project_id: str | None = None
    running: bool = False


class AnalysisOverview(ProviderModel):
    projects: list[AnalysisProject] = Field(default_factory=list)
    workers: list[AnalysisWorker] = Field(default_factory=list)


class CoverageStatistics(StrictModel):
    evaluated_functions: int
    average_effective_score: float
    average_raw_score: float
    complete_80_plus: int
    complete_80_plus_percent: float
    strong_60_79: int
    strong_60_79_percent: float
    partial_40_59: int
    partial_40_59_percent: float
    low_under_40: int
    low_under_40_percent: float
    custom_named: int
    plate_documented: int
    prototype_set: int
    return_type_resolved: int


class CoverageResult(CoverageStatistics):
    project_id: str
    program: str
    total_functions: int
    approximate: bool
    sample_size: int


class AnalysisSession(ProviderModel):
    session: str
