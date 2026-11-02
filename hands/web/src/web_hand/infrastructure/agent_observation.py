"""Record an existing agent reply without dispatching or renewing browser authority."""

import base64
import binascii
import time

from pydantic import ValidationError

from node_protocol.effect import EffectPermit, NodeEffectPermit
from runtime_peer.browser_receipts import BrowserPreview
from web_hand.domain.agent_observation import (
    AgentBrowserFrame,
    AgentBrowserObservations,
    AgentBrowserOwner,
)

from .browser_ipc import BrowserReply


def capture_agent_preview(
    observations: AgentBrowserObservations,
    generation: int,
    permit: EffectPermit,
    tool: str,
    reply: BrowserReply,
) -> None:
    if not isinstance(permit, NodeEffectPermit) or tool != "local_browser_preview":
        return
    result = reply.result
    if result is None or result.is_error or result.structured_content is None:
        return
    try:
        preview = BrowserPreview.model_validate(result.structured_content)
        if preview.mime_type != "image/png" or len(preview.data_base64) > 1_000_000:
            return
        frame = AgentBrowserFrame(
            AgentBrowserOwner(
                permit.project_uuid,
                permit.placement_uuid,
                permit.actor_uuid,
                permit.agent_session_uuid,
                permit.grant_revision,
            ),
            permit.request_uuid,
            time.time(),
            preview.page_id,
            preview.url,
            preview.title,
            base64.b64decode(preview.data_base64, validate=True),
        )
    except (ValidationError, ValueError, binascii.Error):
        return
    observations.capture(generation, frame)
