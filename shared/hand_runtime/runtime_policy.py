"""Immutable signed placement policy; authority leases remain independent."""

import os

from node_protocol.models import RuntimePolicy


def runtime_policy() -> RuntimePolicy:
    return RuntimePolicy.model_validate_json(os.environ.get("BRIAREUS_RUNTIME_POLICY", "{}"))


def child_policy_json() -> str:
    """Encode the existing process environment value without a dictionary contract."""
    return runtime_policy().model_dump_json()
