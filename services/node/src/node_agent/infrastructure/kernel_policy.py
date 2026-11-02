"""Execute only the fixed bridge-owner netfilter commands from application plans."""

from node_agent.application.network_policy import PolicyNamespace
from node_agent.domain.network_policy import NetworkPolicy
from node_agent.domain.policy_readback import PolicySnapshot, RemovalPlan, Rule

from .kernel_readback import _run, _saved_rules, _verify_bridge, namespace_facts


class KernelNetworkPolicy:
    def namespace(self) -> PolicyNamespace:
        facts = namespace_facts()
        return PolicyNamespace(facts.netns_inode, facts.rootless_owner_uid)

    def verify_bridge(self, policy: NetworkPolicy) -> None:
        _verify_bridge(policy)

    def saved(self, family: int) -> PolicySnapshot:
        chains, rules = _saved_rules(family)
        return PolicySnapshot(frozenset(chains), tuple(rules))

    def restore(self, family: int, script: str) -> None:
        binary = "iptables-restore" if family == 4 else "ip6tables-restore"
        _run([binary, "--wait", "3", "--noflush"], stdin_text=script)

    def insert(self, family: int, hook: Rule) -> None:
        binary = "iptables" if family == 4 else "ip6tables"
        _run([binary, "--wait", "3", "-I", hook[1], "1", *hook[2:]])

    def remove(self, plan: RemovalPlan) -> None:
        binary = "iptables" if plan.family == 4 else "ip6tables"
        for rule in plan.references:
            _run([binary, "--wait", "3", "-D", rule[1], *rule[2:]])
        for chain in sorted(plan.chains):
            _run([binary, "--wait", "3", "-F", chain])
        for chain in sorted(plan.chains):
            _run([binary, "--wait", "3", "-X", chain])
