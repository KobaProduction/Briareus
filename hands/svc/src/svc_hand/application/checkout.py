"""Refresh one canonical repository and create or reuse a non-destructive worktree."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from svc_hand.domain.local_git import CheckoutReceipt, CheckoutRequest


class CheckoutStorage(Protocol):
    def lock(self) -> AbstractContextManager[None]: ...
    def existing(self, mode: str) -> CheckoutReceipt | None: ...
    def initialize(self) -> None: ...
    def refresh(self) -> None: ...
    def default_ref(self) -> str: ...
    def resolve_ref(self, selected: str) -> str: ...
    def validate_branch(self, branch: str) -> None: ...
    def create(self, branch: str, selected: str) -> None: ...
    def snapshot(self, branch: str) -> None: ...
    def receipt(self, request: CheckoutRequest, branch: str) -> CheckoutReceipt: ...


@dataclass(frozen=True)
class CheckoutRepository:
    storage: CheckoutStorage

    def execute(self, request: CheckoutRequest) -> CheckoutReceipt:
        with self.storage.lock():
            existing = self.storage.existing(request.mode)
            if existing is not None:
                return existing
            self.storage.initialize()
            self.storage.refresh()
            selected = request.ref.strip() or self.storage.default_ref()
            selected = self.storage.resolve_ref(selected)
            branch = request.branch.strip() or "agents/" + uuid4().hex
            self.storage.validate_branch(branch)
            self.storage.create(branch, selected)
            if request.mode == "snapshot":
                self.storage.snapshot(branch)
            return self.storage.receipt(request, branch)
