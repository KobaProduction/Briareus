import logging
from typing import Literal

import httpx
from briareus_environment_models import ProcessSettings
from briareus_oidc import OidcTokenSettings
from pydantic import Field, SecretStr, ValidationError

from ._models import ErrorCode, NodeRegistrationError, NodeSpec, RegistryConfig
from ._zitadel import ZitadelRoleRegistry

logger = logging.getLogger(__name__)


class NodeProvisioningSettings(ProcessSettings):
    provider: Literal["zitadel"] = Field(validation_alias="OIDC_PROVISIONING_PROVIDER")
    token: SecretStr = Field(validation_alias="OIDC_PROVISIONING_TOKEN", repr=False)


def ensure_node_role(identity: OidcTokenSettings, provisioning: NodeProvisioningSettings) -> bool:
    try:
        node = NodeSpec(node_id=identity.node_id)
        config = RegistryConfig(
            issuer=identity.issuer_url, project_id=identity.audience, token=provisioning.token
        )
    except ValidationError:
        raise NodeRegistrationError(ErrorCode.CONFIGURATION) from None
    with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
        created = ZitadelRoleRegistry(config, client).ensure(node)
    logger.info("Node role ready node=%s created=%s", node.node_id, created)
    return created
