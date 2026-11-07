import os
import subprocess

from ._models import ErrorCode, NodeRegistrationError, NodeSpec


def run_deployment(command: list[str], node: NodeSpec) -> int:
    """Pass public node settings to the installer, never the administrative credential."""
    if not command:
        return 0
    environment = os.environ.copy()
    environment.pop("ZITADEL_PROVISIONING_TOKEN", None)
    environment.update(
        OIDC_REQUIRED_ROLE=node.node_id,
        MCP_PUBLIC_BASE_URL=node.origin,
        CONTROL_PANEL_PUBLIC_BASE_URL=node.origin,
    )
    try:
        return subprocess.run(command, env=environment, check=False).returncode
    except OSError:
        raise NodeRegistrationError(ErrorCode.DEPLOYMENT, node.node_id) from None
