"""Named MCP and scope wire contracts consumed by the human module workflow."""

from dataclasses import dataclass
from uuid import UUID

from control_panel_api.domain.module_preparation import PreparationEvidence
from runtime_peer.human_scope import HumanScopeReceipt
from runtime_peer.human_scope import ScopeItem as ScopeItem
from runtime_peer.human_scope import ScopeResource as ScopeResource

from .module_commands import HumanToolCommand

ModuleScope = HumanScopeReceipt


@dataclass(frozen=True, slots=True)
class McpExchangeResult[Reply]:
    reply: Reply
    evidence: PreparationEvidence


@dataclass(frozen=True, slots=True)
class ModuleRequest:
    project_uuid: UUID
    command: HumanToolCommand | None


type HumanModuleReply[Reply] = ModuleScope | Reply
