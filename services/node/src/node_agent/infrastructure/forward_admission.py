"""Native placement attestation follows durable, signed forwarding admission."""

import logging
import os
import stat

from node_agent.application.control import NodeControl
from node_agent.controller import Controller
from node_agent.docker_engine import DEPLOYMENT_LABEL, NODE_LABEL, SPEC_LABEL, EngineFailure
from node_agent.journal import Journal, JournalUnavailable, OperationConflict
from node_protocol.forward import TransportProof

from .container_models import ContainerInspection
from .execution_tasks import NodeExecutionTasks
from .process_state import process_state

LOG = logging.getLogger(__name__)


class ForwardAdmission:
    def __init__(
        self,
        controller: Controller,
        journal: Journal,
        control: NodeControl,
        tasks: NodeExecutionTasks,
    ) -> None:
        self._controller, self._journal, self._control, self._tasks = (
            controller,
            journal,
            control,
            tasks,
        )

    async def __call__(self, proof: TransportProof, gateway_signature: str) -> str:
        try:
            await self._control.initialize()
            if self._tasks.draining() or not self._controller.node.enabled:
                raise ValueError("Node admission disabled")
            private_gateway_socket()
            container = await self._journal.admit_forward(proof, gateway_signature)
            current = await self._controller.engine.inspect(container)
            if current is None or not self._matches(current, proof):
                LOG.warning("Node placement unavailable module=%s", proof.module)
                raise ValueError("Current healthy placement required")
            if (
                await self._journal.forward_target(proof, gateway_signature) != container
                or not self._accepting()
            ):
                raise ValueError("Current healthy placement required")
        except (OperationConflict, JournalUnavailable) as error:
            LOG.warning(
                "Node journal admission unavailable module=%s exception=%s cause=%s",
                proof.module,
                type(error).__name__,
                type(error.__cause__).__name__,
            )
            raise ValueError("Current placement admission required") from None
        except EngineFailure:
            raise ValueError("Placement runtime unavailable") from None
        return "http://node-gateway/internal/v1/node/mcp"

    def _accepting(self) -> bool:
        # Read mutable controller authority again after awaiting the journal.
        return self._controller.node.enabled and not self._tasks.draining()

    @staticmethod
    def _matches(current: ContainerInspection, proof: TransportProof) -> bool:
        state = process_state(current.state)
        labels = current.config.labels
        return (
            state.running is True
            and state.health == "healthy"
            and labels.get(NODE_LABEL) == str(proof.node_uuid)
            and labels.get(DEPLOYMENT_LABEL) == str(proof.placement_uuid)
            and labels.get(SPEC_LABEL) == proof.fingerprint
        )


def private_gateway_socket() -> None:
    metadata = os.lstat("/node-link/gateway.sock")
    if (
        not stat.S_ISSOCK(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        raise ValueError("Private node Gateway socket required")
