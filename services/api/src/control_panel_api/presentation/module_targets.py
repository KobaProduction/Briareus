"""The existing per-module human tool allowlists, shared by ingress and composition."""

from control_panel_api.domain.module_preparation import ModuleTarget
from node_protocol.files import READ_TOOLS, WRITE_TOOLS
from runtime_peer.terminal_arguments import TERMINAL_ARGUMENTS

BROWSER_TOOLS = frozenset(
    "local_browser_" + name
    for name in (
        "status",
        "pages",
        "open",
        "snapshot",
        "back",
        "forward",
        "reload",
        "close_page",
        "set_viewport",
        "click",
        "fill",
        "press",
        "select_option",
        "preview",
        "reopen_closed_page",
        "settings",
        "input",
    )
)

BROWSER_CONTROLS = frozenset({"web_operation_start", "web_operation_poll", "web_operation_cancel"})

TERMINAL_TOOLS = frozenset(TERMINAL_ARGUMENTS)

FILES_TOOLS = READ_TOOLS | WRITE_TOOLS

ANALYSIS_TOOLS = frozenset(
    {"analysis_tools", "analysis_call", "analysis_start", "analysis_poll", "analysis_cancel"}
)

BROWSER_TARGET = ModuleTarget("web", "browser", BROWSER_TOOLS, BROWSER_CONTROLS)
TERMINAL_TARGET = ModuleTarget("terminal", "terminal", TERMINAL_TOOLS)
FILES_TARGET = ModuleTarget("files", "files", FILES_TOOLS)
ANALYSIS_TARGET = ModuleTarget("reverse", "analysis", ANALYSIS_TOOLS)

_TARGETS = {
    "browser": BROWSER_TARGET,
    "terminal": TERMINAL_TARGET,
    "files": FILES_TARGET,
    "analysis": ANALYSIS_TARGET,
}


def module_target(method: str) -> ModuleTarget:
    return _TARGETS[method.partition(".")[0]]
