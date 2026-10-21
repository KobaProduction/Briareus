"""Existing SigNoz/Coolify tools with per-effect credentials and public-only proxy."""
from modules.observability.context import ObservabilityRuntimeContext
from modules.observability.tools import register_observability_tools
from modules.coolify.client import CoolifyClient
from modules.signoz.client import SigNozClient
from .node_proxy import provider_connection


class NodeCoolifyClient(CoolifyClient):
    def _new_connection(self):
        return provider_connection(self.base_url, verify_tls=self.account.verify_tls,
            ca_cert_pem=self.account.ca_cert_pem, timeout=self.timeout_seconds)


class NodeSigNozClient(SigNozClient):
    def _new_connection(self):
        return provider_connection(self.base_url, verify_tls=self.account.verify_tls,
            ca_cert_pem=self.account.ca_cert_pem, timeout=self.timeout_seconds)


class NodeInfrastructureContext(ObservabilityRuntimeContext):
    def signoz(self, account_id):
        return NodeSigNozClient(self.admin_api.resolve_account(account_id, provider="signoz"))

    def coolify(self, account_id):
        return NodeCoolifyClient(self.admin_api.resolve_account(account_id, provider="coolify"))


def register_source_tools(mcp, accounts, policies=None):
    context = NodeInfrastructureContext(accounts)
    register_observability_tools(mcp, context)
    return (context,)
