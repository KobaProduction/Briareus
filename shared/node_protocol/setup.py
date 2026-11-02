"""Public Core-to-Node installation inputs; no storage or credential authority."""

from pydantic import ConfigDict, Field

from .models import Contract, NodeRecord, ResourceLimits


class JournalSetup(Contract):
    model_config = ConfigDict(strict=True)

    target: str = Field(min_length=3, max_length=512)
    ca_certificate: str = Field(min_length=1, max_length=65536)


class NodeSetup(Contract):
    model_config = ConfigDict(strict=True)

    node_record: NodeRecord
    core_verify_key: str
    gateway_verify_key: str
    runtime_uid: int
    runtime_user: str
    runtime_gid: int
    rootless_budget: ResourceLimits
    endpoint: str
    origin_approved: bool
    journal: JournalSetup
