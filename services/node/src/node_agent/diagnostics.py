"""Project only authoritative Docker state into bounded public failure facts."""

from node_protocol.diagnostics import FailureDiagnostic

from .domain.readiness import ProcessState
from .infrastructure.container_models import InspectedState
from .infrastructure.process_state import process_state

# Exact internal messages only. Arbitrary exceptions, paths, provider error
# text, health Output and credentials are never serialized or substring-matched.
REASONS = {
    "Execution network address conflict": "network_address_conflict",
    "Workspace helper cleanup is unresolved": "workspace_cleanup_uncertain",
    "Workspace helper recovery requires controller restart": "workspace_cleanup_uncertain",
    "Workspace initialization refused": "workspace_initialization_failed",
    "Workspace initializer exceeded its deadline": "workspace_initialization_failed",
    "Refusing foreign or host-backed workspace volume": "workspace_identity_unverified",
    "Conflicting workspace initializer; explicit recovery required": (
        "workspace_identity_unverified"
    ),
    "Workspace helper identity changed": "workspace_identity_unverified",
    "Refusing to reap an unverified workspace helper": "workspace_identity_unverified",
    "Workspace helper changed during recovery": "workspace_identity_unverified",
    "Direct network helper cleanup unresolved": "network_policy_cleanup_uncertain",
    "Direct network policy helper refused": "network_policy_failed",
    "Direct network helper exceeded deadline": "network_policy_failed",
    "Policy helper result unavailable": "network_policy_failed",
    "Direct network kernel readback differs from plan": "network_policy_unverified",
    "Policy helper ownership changed": "network_policy_unverified",
    "Conflicting direct network helper": "network_policy_unverified",
    "Refusing to reap an unverified direct network helper": "network_policy_unverified",
    "Inner Docker engine unavailable": "engine_unavailable",
    "Inner Docker operation rejected": "engine_request_rejected",
    "Rootless socket ownership mismatch": "rootless_unverified",
    "Rootless runtime with enforceable cgroup quotas required": "rootless_unverified",
    "Approved image pull rejected": "pull_failed",
    "Image pull response exceeds budget": "pull_failed",
    "Approved image pull failed": "pull_failed",
    "Approved image delivery unavailable": "pull_failed",
}


def state_diagnostic(
    stage: str,
    state: InspectedState,
    *,
    component: str = "worker",
    timeout: bool = False,
) -> FailureDiagnostic:
    facts = process_state(state)
    return diagnostic_from_state(stage, facts, component=component, timeout=timeout)


def diagnostic_from_state(
    stage: str,
    facts: ProcessState,
    *,
    component: str = "worker",
    timeout: bool = False,
) -> FailureDiagnostic:
    return FailureDiagnostic.model_validate(
        {
            "stage": stage,
            "component": component,
            "reason": facts.failure_reason(helper=component == "egress", timed_out=timeout),
            "exit_code": facts.exit_code,
            "health_status": facts.health,
            "oom_killed": facts.oom_killed,
            "health_exit_code": facts.probe_exit_code,
        }
    )
