"""Analysis summary returned by the MCP adapter."""

from typing import Literal, Self

from domain.analysis import CoverageReport
from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator


class AnalysisCoverage(RootModel[CoverageReport]):
    """A concrete domain report serialized with the existing flat response shape."""


class AnalysisReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisProjectIdentity(AnalysisReadModel):
    project_id: str
    name: str
    path: str


class AnalysisActivity(AnalysisReadModel):
    in_flight: int = 0
    queued: int = 0
    running: bool = False
    current_operation: str | None = None
    last_used_at: str | None = None


class AnalysisWorker(AnalysisActivity):
    worker_index: int
    project_id: str | None
    project_name: str | None
    idle_seconds: float | None
    idle_timeout_seconds: float
    enabled: bool
    auto_release_eligible: bool
    healthy: bool
    error: str | None


class AnalysisProjectSession(AnalysisProjectIdentity, AnalysisActivity):
    session: Literal["active", "available"]
    worker_index: int | None = None


class AnalysisProject(AnalysisProjectSession):
    group: str | None = None


class AnalysisOverview(AnalysisReadModel):
    projects: list[AnalysisProject]
    workers: list[AnalysisWorker] = Field(default_factory=list)
    count: int
    worker_count: int


class AnalysisProjectOpened(AnalysisProjectIdentity):
    session: Literal["active"]
    worker_index: int
    in_flight: int = 0


class AnalysisProjectReleased(AnalysisReadModel):
    project_id: str
    released: bool
    closed: bool | None = None
    reason: Literal["not_active"] | None = None

    @model_validator(mode="after")
    def matching_outcome(self) -> Self:
        if self.released:
            valid = self.closed is not None and self.reason is None
        else:
            valid = self.closed is None and self.reason == "not_active"
        if not valid:
            raise ValueError("Project release details do not match the release outcome")
        return self


class AnalysisProjectDeleted(AnalysisProjectIdentity):
    deleted: Literal[True]


class AnalysisWorkerChanged(AnalysisWorker):
    changed: bool


class AnalysisWorkerQueueCleared(AnalysisWorker):
    cancelled_total: int
    cancelled_queued: int
    cancelled_running: int


class AnalysisWorkerRecovered(AnalysisWorkerQueueCleared):
    recovered: Literal[True]
    restart_method: str
    recovery_ms: float
    previous_project_id: str | None
    previous_project_name: str | None


class AnalysisProjectFile(AnalysisReadModel):
    name: str
    path: str
    content_type: str
    version: int
    is_read_only: bool
    is_versioned: bool


class AnalysisProjectFiles(AnalysisReadModel):
    project_name: str
    current_folder: str
    folders: list[str]
    files: list[AnalysisProjectFile]


class AnalysisOpenProgram(AnalysisReadModel):
    name: str
    path: str
    is_current: bool
    executable_path: str
    language: str
    compiler: str
    image_base: str
    memory_size: int
    function_count: int
    has_multiple_address_spaces: bool
    has_overlay_spaces: bool
    overlay_space_count: int


class AnalysisOpenPrograms(AnalysisReadModel):
    programs: list[AnalysisOpenProgram]
    count: int
    current_program: str


class AnalysisSessionPolicy(AnalysisReadModel):
    idle_timeout_seconds: float
    auto_release_enabled: bool


class AnalysisSessionSettings(AnalysisSessionPolicy):
    settings_path: str
    source: Literal["persistent", "environment_default"]


class AnalysisSettingsUnavailable(AnalysisSessionPolicy):
    source: Literal["unavailable"] = "unavailable"
