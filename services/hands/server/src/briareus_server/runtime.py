"""Server composition root: one filesystem mount, files and terminal capabilities."""

from briareus_control_panel_client.settings import ControlPanelClientSettings
from briareus_hand_runtime.runtime_common import (
    build_private_mcp,
    management_client,
    private_http_app,
)
from briareus_hand_runtime.settings import PrivateRuntimeSettings
from briareus_tool_annotations import DESTRUCTIVE_LOCAL, READ_ONLY_LOCAL, WRITE_LOCAL
from briareus_workspace.settings import FileSettings
from briareus_workspace.workspace_store import WorkspaceFileStore

from briareus_server.files.file_tools import register_file_tools
from briareus_server.terminal.manager import TerminalManager
from briareus_server.terminal.settings import TerminalSettings
from briareus_server.terminal.tools import register_terminal_tools

_private_settings = PrivateRuntimeSettings()
_management = management_client(ControlPanelClientSettings())
_file_settings = FileSettings()
_terminal_settings = TerminalSettings()
mcp = build_private_mcp("server", _management)
_workspace = WorkspaceFileStore(_file_settings.workspace_root)
_manager = TerminalManager(_terminal_settings, _management)
register_file_tools(
    mcp,
    READ_ONLY_LOCAL,
    WRITE_LOCAL,
    DESTRUCTIVE_LOCAL,
    workspace=_workspace,
    max_file_bytes=_file_settings.upload_max_bytes,
)
register_terminal_tools(mcp, _manager)
app = private_http_app(mcp, _private_settings)
