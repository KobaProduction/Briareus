"""Truthful browser readiness requires a live process, CDP and a usable context."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserReadiness:
    process_running: bool
    cdp_reachable: bool
    context_usable: bool

    def __post_init__(self) -> None:
        if self.cdp_reachable and not self.process_running:
            raise ValueError("CDP readiness requires a running browser process")
        if self.context_usable and not self.cdp_reachable:
            raise ValueError("Browser context readiness requires reachable CDP")

    @property
    def running(self) -> bool:
        return self.process_running and self.cdp_reachable and self.context_usable
