"""Requests supported by the pinned private Ghidra MCP provider."""

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict


class AnalysisCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tool_name: ClassVar[str]


class ListProjects(AnalysisCommand):
    tool_name = "list_projects"


class ProjectSelection(AnalysisCommand):
    project_id: str


class ProjectSessionInfo(ProjectSelection):
    tool_name = "project_session_info"


class OpenProject(ProjectSelection):
    tool_name = "open_project"


class ReleaseProject(ProjectSelection):
    tool_name = "release_project_session"
    close_project: Literal[True] = True


class ProjectFiles(ProjectSelection):
    tool_name = "list_project_files"
    folder: str


class OpenPrograms(ProjectSelection):
    tool_name = "list_open_programs"


class CreateProject(AnalysisCommand):
    tool_name = "create_project"
    name: str
    parent_dir: str


class DeleteProject(ProjectSelection):
    tool_name = "delete_project"


class WorkerSelection(AnalysisCommand):
    worker_index: int


class SetWorkerEnabled(WorkerSelection):
    tool_name = "set_worker_enabled"
    enabled: bool
    close_project: bool


class ClearWorkerQueue(WorkerSelection):
    tool_name = "clear_worker_queue"


class RecoverWorker(WorkerSelection):
    tool_name = "recover_worker"
    timeout_seconds: float


class ProgramSelection(ProjectSelection):
    program: str


class FunctionCount(ProgramSelection):
    tool_name = "get_function_count"


class ListFunctions(ProgramSelection):
    tool_name = "list_functions_enhanced"
    offset: int = 0
    limit: int


class FunctionCompleteness(ProgramSelection):
    tool_name = "analyze_function_completeness"
    addresses: str
    compact: Literal[True] = True


class SessionSettings(AnalysisCommand):
    tool_name = "project_session_settings"


class SetIdleTimeout(AnalysisCommand):
    tool_name = "set_project_idle_timeout"
    idle_timeout_seconds: float
