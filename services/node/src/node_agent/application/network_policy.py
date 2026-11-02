"""Read back before workers start; preflight both families before any removal."""

from dataclasses import dataclass
from typing import Protocol

from node_agent.domain.network_policy import NetworkPolicy, PolicyUnavailable
from node_agent.domain.policy_readback import (
    PolicySnapshot,
    RemovalPlan,
    Rule,
    removal_plan,
    require_removed,
    require_saved,
)

from ._runtime_binding import _RuntimeBinding


@dataclass(frozen=True, slots=True)
class PolicyNamespace:
    netns_inode: int
    rootless_owner_uid: int


class KernelPolicyPort(Protocol):
    def namespace(self) -> PolicyNamespace: ...

    def verify_bridge(self, policy: NetworkPolicy) -> None: ...

    def saved(self, family: int) -> PolicySnapshot: ...

    def restore(self, family: int, script: str) -> None: ...

    def insert(self, family: int, hook: Rule) -> None: ...

    def remove(self, plan: RemovalPlan) -> None: ...


class ManageNetworkPolicy(_RuntimeBinding[KernelPolicyPort]):
    def readback(self, policy: NetworkPolicy) -> PolicyNamespace:
        facts = self.runtime.namespace()
        self.runtime.verify_bridge(policy)
        for family in (4, 6):
            require_saved(policy, family, self.runtime.saved(family))
        return facts

    def apply(self, policy: NetworkPolicy) -> PolicyNamespace:
        self.runtime.namespace()
        self.runtime.verify_bridge(policy)
        for family in (4, 6):
            snapshot = self.runtime.saved(family)
            if family == 4 and "DOCKER-USER" not in snapshot.chains:
                raise PolicyUnavailable("Docker iptables forwarding anchor is unavailable")
            self.runtime.restore(family, policy.restore_script(family))
            snapshot = self.runtime.saved(family)
            for hook in policy.hooks(family):
                if hook not in snapshot.rules:
                    self.runtime.insert(family, hook)
        return self.readback(policy)

    def remove(self, policy: NetworkPolicy) -> PolicyNamespace:
        facts = self.runtime.namespace()
        self.runtime.verify_bridge(policy)
        plans = tuple(removal_plan(policy, family, self.runtime.saved(family)) for family in (4, 6))
        for plan in plans:
            self.runtime.remove(plan)
        for family in (4, 6):
            require_removed(policy, family, self.runtime.saved(family))
        return facts
