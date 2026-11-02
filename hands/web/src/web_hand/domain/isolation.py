"""Attested OS facts distinguish the trusted parent from its unprivileged child."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BrowserPrivileges:
    uid: int
    no_new_privileges: bool
    capabilities: int
    readonly_root: bool
    docker_socket: bool
    deployment_present: bool

    def require_child(self) -> None:
        if (
            self.uid != 1000
            or not self.no_new_privileges
            or self.capabilities != 0
            or not self.readonly_root
            or self.docker_socket
            or self.deployment_present
        ):
            raise ValueError("Unprivileged isolated browser child required")


@dataclass(frozen=True, slots=True)
class BrowserIsolation(BrowserPrivileges):
    interfaces: frozenset[str]

    def require_supervisor(self) -> None:
        if (
            self.uid != 0
            or not self.no_new_privileges
            or self.capabilities != (1 << 5 | 1 << 6 | 1 << 7)
            or not self.readonly_root
            or self.docker_socket
            or self.interfaces != frozenset({"lo", "eth0"})
        ):
            raise ValueError("Isolated rootless browser supervisor placement required")
