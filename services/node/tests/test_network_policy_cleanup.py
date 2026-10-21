"""Pure exact-scope cleanup checks; these are not kernel acceptance."""
import unittest
from unittest.mock import patch
from uuid import uuid4

from node_agent.network_policy import NetworkPolicy,PolicyUnavailable,remove


class PolicyCleanupTests(unittest.TestCase):
    def setUp(self):
        self.policy=NetworkPolicy(str(uuid4()),str(uuid4()),"br-0123456789ab","172.30.9.0/24",("1.1.1.1",))
        self.facts={"netns_inode":123,"rootless_owner_uid":2201,"capabilities":"NET_ADMIN"}
        self.states={family:[{self.policy.chain(family,"F"),self.policy.chain(family,"I"),"UNRELATED"},
            self.policy.rules(family)+self.policy.hooks(family)+[("-A","UNRELATED","-j","ACCEPT")]] for family in (4,6)}
        self.commands=[]

    def saved(self,family):
        chains,rules=self.states[family]
        return set(chains),list(rules)

    def run_command(self,args):
        self.commands.append(args)
        family=4 if args[0]=="iptables" else 6
        chains,rules=self.states[family]
        op,chain=args[3:5]
        if op=="-D":rules.remove(("-A",chain,*args[5:]))
        elif op=="-F":rules[:]=[rule for rule in rules if rule[1]!=chain]
        elif op=="-X":chains.remove(chain)
        else:raise AssertionError(args)
        return ""

    def cleanup(self):
        with patch("node_agent.network_policy.namespace_facts",return_value=self.facts),patch(
            "node_agent.network_policy._verify_bridge"),patch("node_agent.network_policy._saved_rules",side_effect=self.saved),patch(
            "node_agent.network_policy._run",side_effect=self.run_command):
            return remove(self.policy)

    def test_removal_preserves_unrelated_chains_and_is_replay_safe(self):
        result=self.cleanup()
        self.assertEqual(result["state"],"removed")
        for family in (4,6):
            self.assertEqual(self.states[family],[{"UNRELATED"},[("-A","UNRELATED","-j","ACCEPT")]])
        count=len(self.commands)
        self.cleanup()
        self.assertEqual(len(self.commands),count)

    def test_foreign_reference_in_second_family_refuses_all_mutation(self):
        self.states[6][1].append(("-A","UNRELATED","-j",self.policy.chain(6,"F")))
        with self.assertRaises(PolicyUnavailable):self.cleanup()
        self.assertEqual(self.commands,[])

    def test_tampered_body_refuses_and_interrupted_empty_chain_can_be_removed(self):
        chain=self.policy.chain(4,"F")
        self.states[4][1].append(("-A",chain,"-j","ACCEPT"))
        with self.assertRaises(PolicyUnavailable):self.cleanup()
        self.assertEqual(self.commands,[])
        self.states[4][1][:]=[rule for rule in self.states[4][1] if rule[1]!=chain]
        self.assertEqual(self.cleanup()["state"],"removed")
