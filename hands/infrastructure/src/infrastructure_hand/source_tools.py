"""Existing SigNoz/Coolify tools with per-effect credentials and public-only proxy."""

from common.tool_registration import ToolRegistrar
from modules.observability.context import ObservabilityRuntimeContext
from modules.observability.tools import register_observability_tools

from hand_runtime.account_lease import InvocationAccounts
from hand_runtime.provider_egress import ProviderConnection
from modules.coolify.client import CoolifyClient
from modules.signoz.client import SigNozClient
from node_protocol.provider_context import InvocationPolicies

from .node_proxy import provider_connection


class NodeCoolifyClient(CoolifyClient):
    def _new_connection(self) -> ProviderConnection:
        return provider_connection(
            self.base_url,
            verify_tls=self.account.verify_tls,
            ca_cert_pem=self.account.ca_cert_pem,
            timeout=self.timeout_seconds,
        )


class NodeSigNozClient(SigNozClient):
    def _new_connection(self) -> ProviderConnection:
        return provider_connection(
            self.base_url,
            verify_tls=self.account.verify_tls,
            ca_cert_pem=self.account.ca_cert_pem,
            timeout=self.timeout_seconds,
        )


class NodeInfrastructureContext(ObservabilityRuntimeContext):
    def signoz(self, account_id: str) -> NodeSigNozClient:
        return NodeSigNozClient(self.admin_api.resolve_account(account_id, provider="signoz"))

    def coolify(self, account_id: str) -> NodeCoolifyClient:
        return NodeCoolifyClient(self.admin_api.resolve_account(account_id, provider="coolify"))


def register_source_tools(
    mcp: ToolRegistrar, accounts: InvocationAccounts, _policies: InvocationPolicies | None = None
) -> tuple[NodeInfrastructureContext]:
    context = NodeInfrastructureContext(accounts)
    register_observability_tools(mcp, context, provider_native=True)
    return (context,)
