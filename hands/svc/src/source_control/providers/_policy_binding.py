"""Typed policy-provider reference for the existing provider middleware constructors."""

from collections.abc import Callable


class _PolicyProviderBinding[PolicyT]:
    def __init__(self, policy_provider: Callable[[], PolicyT]) -> None:
        self.policy_provider = policy_provider
