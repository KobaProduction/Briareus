"""Pure exact-scope cleanup checks; these are not kernel acceptance."""

import unittest
from dataclasses import dataclass
from unittest.mock import patch
from uuid import uuid4

from node_agent.domain.policy_readback import Rule
from node_agent.infrastructure.kernel_readback import NamespaceFacts
from node_agent.network_policy import NetworkPolicy, PolicyRemoval, PolicyUnavailable, remove


@dataclass
class RuleState:
    chains: set[str]
    rules: list[Rule]


class PolicyCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = NetworkPolicy(
            str(uuid4()), str(uuid4()), "br-0123456789ab", "172.30.9.0/24", ("1.1.1.1",)
        )
        self.facts = NamespaceFacts(netns_inode=123, rootless_owner_uid=2201)
        self.states = {
            family: RuleState(
                {self.policy.chain(family, "F"), self.policy.chain(family, "I"), "UNRELATED"},
                self.policy.rules(family)
                + self.policy.hooks(family)
                + [("-A", "UNRELATED", "-j", "ACCEPT")],
            )
            for family in (4, 6)
        }
        self.commands: list[list[str]] = []

    def saved(self, family: int) -> tuple[set[str], list[Rule]]:
        state = self.states[family]
        return set(state.chains), list(state.rules)

    def run_command(self, args: list[str]) -> str:
        self.commands.append(args)
        family = 4 if args[0] == "iptables" else 6
        chains, rules = self.states[family].chains, self.states[family].rules
        op, chain = args[3:5]
        if op == "-D":
            rules.remove(("-A", chain, *args[5:]))
        elif op == "-F":
            rules[:] = [rule for rule in rules if rule[1] != chain]
        elif op == "-X":
            chains.remove(chain)
        else:
            raise AssertionError(args)
        return ""

    def cleanup(self) -> PolicyRemoval:
        with (
            patch(
                "node_agent.infrastructure.kernel_policy.namespace_facts", return_value=self.facts
            ),
            patch("node_agent.infrastructure.kernel_policy._verify_bridge"),
            patch("node_agent.infrastructure.kernel_policy._saved_rules", side_effect=self.saved),
            patch("node_agent.infrastructure.kernel_policy._run", side_effect=self.run_command),
        ):
            return remove(self.policy)

    def test_removal_preserves_unrelated_chains_and_is_replay_safe(self) -> None:
        result = self.cleanup()
        self.assertEqual(result.state, "removed")
        for family in (4, 6):
            self.assertEqual(
                self.states[family], RuleState({"UNRELATED"}, [("-A", "UNRELATED", "-j", "ACCEPT")])
            )
        count = len(self.commands)
        self.cleanup()
        self.assertEqual(len(self.commands), count)

    def test_foreign_reference_in_second_family_refuses_all_mutation(self) -> None:
        self.states[6].rules.append(("-A", "UNRELATED", "-j", self.policy.chain(6, "F")))
        with self.assertRaises(PolicyUnavailable):
            self.cleanup()
        self.assertEqual(self.commands, [])

    def test_tampered_body_refuses_and_interrupted_empty_chain_can_be_removed(self) -> None:
        chain = self.policy.chain(4, "F")
        self.states[4].rules.append(("-A", chain, "-j", "ACCEPT"))
        with self.assertRaises(PolicyUnavailable):
            self.cleanup()
        self.assertEqual(self.commands, [])
        self.states[4].rules[:] = [rule for rule in self.states[4].rules if rule[1] != chain]
        self.assertEqual(self.cleanup().state, "removed")
