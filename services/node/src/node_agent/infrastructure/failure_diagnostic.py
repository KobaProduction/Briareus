"""Inspect exact placement identities before publishing bounded failure facts."""

from node_agent.diagnostics import state_diagnostic
from node_agent.docker_engine import DEPLOYMENT_LABEL, SPEC_LABEL, DockerEngine, EngineFailure
from node_agent.egress_runtime import companion_name
from node_agent.runtime_profiles import EGRESS_REQUIRED, ROLE_LABEL
from node_protocol import Deployment
from node_protocol.diagnostics import FailureDiagnostic

from .container_models import ContainerInspection
from .runtime_bindings import _EngineBinding


def matches(current: ContainerInspection, desired: Deployment) -> bool:
    return (
        current.config.labels.get(DEPLOYMENT_LABEL) == str(desired.id)
        and current.config.labels.get(SPEC_LABEL) == desired.fingerprint
    )


class InspectFailure(_EngineBinding[DockerEngine]):
    async def execute(
        self,
        stage: str,
        container: str | None,
        desired: Deployment,
        *,
        deadline_expired: bool,
    ) -> FailureDiagnostic:
        if stage == "pulling":
            return self._fallback(stage, "engine", "pull_failed")
        try:
            current = await self._engine.inspect(container) if container else None
            if current is not None and matches(current, desired):
                worker = state_diagnostic(stage, current.state, timeout=deadline_expired)
                if (
                    worker.health_status == "healthy"
                    and current.state.running is True
                    and current.config.labels.get(EGRESS_REQUIRED) == "true"
                ):
                    return await self._helper(stage, desired, deadline_expired)
                return worker
        except (EngineFailure, OSError, ValueError, KeyError, TypeError):
            pass
        return self._fallback(
            stage, "controller", "readiness_timeout" if deadline_expired else "unknown"
        )

    async def _helper(self, stage: str, desired: Deployment, expired: bool) -> FailureDiagnostic:
        name = "/" + companion_name(desired.container_name)
        for row in await self._engine.containers(desired.node_uuid):
            if name not in row.names:
                continue
            helper = await self._engine.inspect(row.identity)
            if (
                helper is not None
                and matches(helper, desired)
                and helper.config.labels.get(ROLE_LABEL) == "egress"
            ):
                return state_diagnostic(stage, helper.state, component="egress", timeout=expired)
        return self._fallback(stage, "egress", "helper_unhealthy")

    @staticmethod
    def _fallback(stage: str, component: str, reason: str) -> FailureDiagnostic:
        return FailureDiagnostic.model_validate(
            {"stage": stage, "component": component, "reason": reason}
        )
