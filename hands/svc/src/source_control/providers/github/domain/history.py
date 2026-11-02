"""Identity-only Git history rewrites preserve content and ordered parent topology."""

from dataclasses import dataclass


class HistoryRewriteError(ValueError):
    """A requested history rewrite violates a content or graph invariant."""


def require_identity_only(
    expected_head: str, identity_source: str, *, preserve_messages: bool, preserve_trees: bool
) -> None:
    if identity_source != "current_agent_app":
        raise HistoryRewriteError("identity_source must be current_agent_app")
    if not expected_head.strip():
        raise HistoryRewriteError("expected_head_sha is required")
    if not preserve_messages or not preserve_trees:
        raise HistoryRewriteError(
            "identity rewrite is identity-only; preserve_messages and preserve_trees must be true"
        )


@dataclass(frozen=True, slots=True)
class GitSignature:
    name: str
    email: str
    date: str = ""


@dataclass(frozen=True, slots=True)
class GitIdentity:
    name: str
    email: str

    def require_complete(self) -> None:
        if not self.name or not self.email:
            raise HistoryRewriteError("current Agent App identity is incomplete")


@dataclass(frozen=True, slots=True)
class GitCommit:
    sha: str
    tree: str
    message: str
    parents: tuple[str, ...]
    author: GitSignature
    committer: GitSignature

    def matches_identity(self, identity: GitIdentity) -> bool:
        return all(
            signature.name == identity.name and signature.email == identity.email
            for signature in (self.author, self.committer)
        )

    def require_rewritten(
        self, original: "GitCommit", parents: tuple[str, ...], identity: GitIdentity
    ) -> None:
        if self.tree != original.tree:
            raise HistoryRewriteError(f"rewritten commit tree mismatch for {original.sha}")
        if self.message != original.message:
            raise HistoryRewriteError(f"rewritten commit message mismatch for {original.sha}")
        if self.parents != parents:
            raise HistoryRewriteError(
                f"rewritten commit parent topology mismatch for {original.sha}"
            )
        if not self.matches_identity(identity):
            raise HistoryRewriteError(f"rewritten commit identity mismatch for {original.sha}")


class CommitGraph:
    """A bounded graph under construction, emitted only in parent-first order."""

    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.commits: dict[str, GitCommit] = {}
        self.visiting: set[str] = set()
        self.order: list[GitCommit] = []

    def enter(self, sha: str) -> bool:
        if sha in self.commits:
            return False
        if sha in self.visiting:
            raise HistoryRewriteError(f"commit graph cycle detected at {sha}")
        if len(self.commits) + len(self.visiting) >= self.maximum:
            raise HistoryRewriteError(
                f"rewrite graph exceeds max_commits={self.maximum}; raise the limit"
            )
        self.visiting.add(sha)
        return True

    def finish(self, commit: GitCommit) -> None:
        self.visiting.remove(commit.sha)
        self.commits[commit.sha] = commit
        self.order.append(commit)


class LinearCommitRange:
    """An exclusive base must be reached through a sequence without merges."""

    def __init__(self, head: str, base: str | None) -> None:
        self.current = head
        self.base = base
        self.reached_base = base is None
        self.newest: list[GitCommit] = []

    def at_base(self) -> bool:
        if self.base is not None and self.current == self.base:
            self.reached_base = True
            return True
        return False

    def accept(self, commit: GitCommit) -> bool:
        if len(commit.parents) > 1:
            raise HistoryRewriteError(
                f"history rewrite supports linear history only; merge commit found: {self.current}"
            )
        self.newest.append(commit)
        if not commit.parents:
            self.reached_base = self.base is None
            return False
        self.current = commit.parents[0]
        return True

    def finish(self) -> tuple[GitCommit, ...]:
        if self.base is not None and not self.reached_base:
            raise HistoryRewriteError("base_sha is not a first-parent ancestor of branch head")
        if not self.newest:
            raise HistoryRewriteError("rewrite range contains no commits")
        return tuple(reversed(self.newest))
