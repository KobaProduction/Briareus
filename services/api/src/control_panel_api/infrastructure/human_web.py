"""Use the existing signed BFF peer; no human execution selector reaches the UI."""

import base64
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import SecretStr

from control_panel_api.domain.oidc_identity import PrivateOidcResourceCredential
from control_panel_api.domain.platform_management import RpcFailure
from runtime_peer import PeerClient
from runtime_peer.human_web import HumanEffectInput, HumanPermitReceipt
from runtime_peer.response_decoding import successful_reply


@dataclass(frozen=True, slots=True)
class PeerHumanEffectPermits:
    peer: PeerClient

    async def issue(
        self,
        *,
        project_uuid: UUID,
        request_uuid: UUID,
        body: bytes,
        credential: PrivateOidcResourceCredential,
        module: Literal["web", "files", "terminal", "reverse"] = "web",
    ) -> str:
        command = HumanEffectInput(
            module=module,
            project_uuid=project_uuid,
            request_uuid=request_uuid,
            bearer=SecretStr(credential.bearer.get_secret_value()),
            body=base64.b64encode(body).decode("ascii"),
        )
        owner = await self.peer.call(
            "/internal/v1/authorization/human-effect",
            {
                "module": command.module,
                "project_uuid": str(command.project_uuid),
                "request_uuid": str(command.request_uuid),
                "bearer": command.bearer.get_secret_value(),
                "body": command.body,
            },
            decode=successful_reply(HumanPermitReceipt.model_validate),
        )
        prefix = "BROWSER" if module == "web" else module.upper()
        if owner.status in {401, 403}:
            raise RpcFailure(prefix + "_PROJECT_ACCESS_REQUIRED")
        if owner.status != 200 or owner.body is None:
            raise RpcFailure(prefix + "_AUTHORITY_UNAVAILABLE")
        return owner.body.permit
