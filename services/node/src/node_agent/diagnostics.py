"""Project only authoritative Docker state into bounded public failure facts."""
from node_protocol.diagnostics import diagnostic_wire

# Exact internal messages only. Arbitrary exceptions, paths, provider error
# text, health Output and credentials are never serialized or substring-matched.
REASONS = {
    "Execution network address conflict": "network_address_conflict",
    "Workspace helper cleanup is unresolved": "workspace_cleanup_uncertain",
    "Workspace helper recovery requires controller restart": "workspace_cleanup_uncertain",
    "Workspace initialization refused": "workspace_initialization_failed",
    "Workspace initializer exceeded its deadline": "workspace_initialization_failed",
    "Refusing foreign or host-backed workspace volume": "workspace_identity_unverified",
    "Conflicting workspace initializer; explicit recovery required": "workspace_identity_unverified",
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


def state_diagnostic(stage, state, *, component="worker", timeout=False):
    state = state if isinstance(state, dict) else {}
    health = state.get("Health", {}).get("Status") if isinstance(state.get("Health"), dict) else "none"
    if health not in {"starting", "healthy", "unhealthy", "none"}:
        health = None
    oom = state.get("OOMKilled") if type(state.get("OOMKilled")) is bool else None
    exited = state.get("Running") is False
    code = state.get("ExitCode") if exited and type(state.get("ExitCode")) is int else None
    if code is not None and not 0 <= code <= 255:
        code = None
    checks = state.get("Health", {}).get("Log") if isinstance(state.get("Health"), dict) else None
    probe = checks[-1].get("ExitCode") if isinstance(checks,list) and checks and isinstance(checks[-1],dict) else None
    if type(probe) is not int or not -1 <= probe <= 255:
        probe = None
    reason = ("oom" if oom is True else "process_exited" if exited else
              "helper_unhealthy" if component == "egress" and health == "unhealthy" else
              "unhealthy" if health == "unhealthy" else "readiness_timeout" if timeout else "unknown")
    return diagnostic_wire(dict(stage=stage, component=component, reason=reason,
        exit_code=code, health_status=health, oom_killed=oom, health_exit_code=probe))
