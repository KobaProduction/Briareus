"""Read-only preparation may retry; the requested effect is dispatched exactly once."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModuleInitialization:
    """A successful MCP handshake, not remote capability documents or authority."""

    protocol_version: str | None


@dataclass(frozen=True, slots=True)
class ModuleTarget:
    module: str
    prefix: str
    tools: frozenset[str]
    controls: frozenset[str] = frozenset()

    @property
    def status_tool(self) -> str:
        if self.module == "reverse":
            return "analysis_tools"
        return "terminal_status" if self.module == "terminal" else "local_browser_status"

    def prepares(self, tool: str, engine: str | None) -> bool:
        if self.module == "reverse":
            return tool in {"analysis_tools", "analysis_call", "analysis_start"} and engine in {
                "ghidra",
                "radare2",
            }
        return (
            tool == self.status_tool
            or (
                self.module == "terminal"
                and tool
                in {
                    "workspace_create",
                    "workspace_list",
                    "workspace_info",
                    "job_list",
                    "job_status",
                }
            )
            or (self.module == "web" and tool == "web_operation_start")
        )


@dataclass(frozen=True, slots=True)
class PreparationEvidence:
    is_error: bool = False
    node_preparing: bool = False
    running: bool = False
    workspace_ready: bool = False
    engine: str | None = None
    tools_ready: bool = False
    pending_operation: bool = False

    def ready(self, module: str, engine: str | None) -> bool:
        if self.is_error:
            return False
        if module == "web":
            return self.running
        if module == "terminal":
            return self.workspace_ready
        return module == "reverse" and self.engine == engine and self.tools_ready
