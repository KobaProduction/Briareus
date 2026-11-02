"""Validate owned kernel chains and preflight both-family removal without effects."""

from dataclasses import dataclass

from .network_policy import BRIDGE, NetworkPolicy, PolicyUnavailable

Rule = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PolicySnapshot:
    chains: frozenset[str]
    rules: tuple[Rule, ...]


@dataclass(frozen=True, slots=True)
class BridgeSnapshot:
    link_kinds: tuple[str | None, ...]
    ipv4_subnets: frozenset[str]


def require_bridge(policy: NetworkPolicy, snapshot: BridgeSnapshot) -> None:
    if snapshot.link_kinds != ("bridge",) or snapshot.ipv4_subnets != {policy.ipv4_subnet}:
        raise PolicyUnavailable("Worker bridge type or IPv4 subnet differs from policy")


@dataclass(frozen=True, slots=True)
class RemovalPlan:
    family: int
    chains: frozenset[str]
    references: tuple[Rule, ...]


def require_prior_hooks(policy: NetworkPolicy, hook: Rule, rules: tuple[Rule, ...]) -> None:
    anchor = [rule for rule in rules if rule[1] == hook[1]]
    if anchor.count(hook) != 1:
        raise PolicyUnavailable("Unique scoped network hook required")
    for earlier in anchor[: anchor.index(hook)]:
        if "!" in earlier or "-i" not in earlier:
            raise PolicyUnavailable("An earlier broad rule can bypass network policy")
        interface = earlier[earlier.index("-i") + 1]
        if not BRIDGE.fullmatch(interface) or interface == policy.bridge:
            raise PolicyUnavailable("An earlier rule can bypass this bridge policy")


def require_saved(policy: NetworkPolicy, family: int, snapshot: PolicySnapshot) -> None:
    if family == 4:
        forwarding = [rule for rule in snapshot.rules if rule[1] == "FORWARD"]
        if not forwarding or forwarding[0] != ("-A", "FORWARD", "-j", "DOCKER-USER"):
            raise PolicyUnavailable("Docker's early forwarding anchor is unavailable")
    owned = {policy.chain(family, "F"), policy.chain(family, "I")}
    if not owned <= snapshot.chains:
        raise PolicyUnavailable("Owned network chains are missing")
    actual = [rule for rule in snapshot.rules if rule[1] in owned]
    if actual != policy.rules(family):
        raise PolicyUnavailable("Owned network rules differ from policy")
    for hook in policy.hooks(family):
        require_prior_hooks(policy, hook, snapshot.rules)


def references_to(owned: set[str], rules: tuple[Rule, ...]) -> tuple[Rule, ...]:
    return tuple(rule for rule in rules if "-j" in rule and rule[rule.index("-j") + 1] in owned)


def removal_plan(policy: NetworkPolicy, family: int, snapshot: PolicySnapshot) -> RemovalPlan:
    owned = {policy.chain(family, "F"), policy.chain(family, "I")}
    present = owned & snapshot.chains
    actual = [rule for rule in snapshot.rules if rule[1] in owned]
    expected = [rule for rule in policy.rules(family) if rule[1] in present]
    for chain in present:
        entries = [rule for rule in actual if rule[1] == chain]
        if entries and entries != [rule for rule in expected if rule[1] == chain]:
            raise PolicyUnavailable("Refusing to remove mismatched bridge policy")
    hooks = policy.hooks(family)
    references = references_to(owned, snapshot.rules)
    if any(rule not in hooks for rule in references) or any(
        references.count(hook) > 1 for hook in hooks
    ):
        raise PolicyUnavailable("Refusing to remove foreign bridge policy references")
    return RemovalPlan(family, frozenset(present), references)


def require_removed(policy: NetworkPolicy, family: int, snapshot: PolicySnapshot) -> None:
    owned = {policy.chain(family, "F"), policy.chain(family, "I")}
    if owned & snapshot.chains or references_to(owned, snapshot.rules):
        raise PolicyUnavailable("Bridge policy removal readback failed")
