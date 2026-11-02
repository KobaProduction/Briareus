"""Verify current kernel observations against trusted public placement facts."""

from typing import Protocol

from terminal_hand.domain.public_network import KernelNetwork, PublicRouting


class NetworkInventory(Protocol):
    def current(self) -> KernelNetwork: ...


class VerifyPublicNetwork:
    def __init__(self, inventory: NetworkInventory) -> None:
        self._inventory = inventory

    def execute(self, routing: PublicRouting) -> None:
        self._inventory.current().require(routing)
