"""Immutable signed placement policy; authority leases remain independent."""
import json
import os
from node_protocol.models import RuntimePolicy


def runtime_policy():
    return RuntimePolicy.model_validate_json(os.environ.get("BRIAREUS_RUNTIME_POLICY", "{}"))


def child_policy_env():
    return {"BRIAREUS_RUNTIME_POLICY": runtime_policy().model_dump_json()}
