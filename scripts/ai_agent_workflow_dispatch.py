"""Verify upstream Git commits and select Hands affected by workflow document changes."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

SOURCE_REPOSITORY = "ArthurKoba/ai-agent-workflow"
SOURCE_REF = "refs/heads/main"
COMMIT = re.compile(r"[0-9a-f]{40}\Z")

# Keep aligned with the build-time allowlist in workflow_sync.py (feature PR #557).
GIT_INPUTS = frozenset(
    {
        "AGENTS.md",
        "skills/git-workflow.md",
        "skills/git-workflow/commits.md",
        "skills/git-workflow/publication.md",
        "skills/orchestration/README.md",
        "skills/orchestration/participants.md",
        "skills/orchestration/cycle.md",
        "skills/orchestration/communication.md",
        "skills/orchestration/pipeline.md",
        "skills/orchestration/workspace.md",
        "docs/REPORTING_PROTOCOL.md",
    }
)
COOLIFY_INPUTS = frozenset(
    {"AGENTS.md", "skills/terminal-operations.md", "docs/MCP_STRATEGY.md"}
)
COOLIFY_PREFIX = "skills/services-deployment/"


def classify_paths(paths: Iterable[str], *, full: bool = False) -> dict[str, bool]:
    files = set(paths)
    git_changed = full or bool(files & GIT_INPUTS)
    coolify_changed = full or bool(files & COOLIFY_INPUTS) or any(
        path.startswith(COOLIFY_PREFIX) and path.endswith(".md") for path in files
    )
    return {
        "github": git_changed,
        "gitlab": git_changed,
        "coolify": coolify_changed,
        "any": git_changed or coolify_changed,
    }


def git(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        check=False,
    )


def changed_files(root: Path, before: str, after: str) -> tuple[list[str], bool]:
    """Validate upstream history; missing base means conservative full refresh."""
    if not COMMIT.fullmatch(before) or not COMMIT.fullmatch(after):
        raise ValueError("Expected 40-character lowercase commit SHAs")
    if git(root, "cat-file", "-e", f"{after}^{{commit}}").returncode:
        raise ValueError("The event's after commit is absent from upstream")
    if git(root, "merge-base", "--is-ancestor", after, "origin/main").returncode:
        raise ValueError("The event's after commit is not on upstream main")
    if before == "0" * 40:
        return [], True
    if git(root, "cat-file", "-e", f"{before}^{{commit}}").returncode:
        return [], True
    if before == after:
        return [], False
    result = git(root, "diff", "--name-only", "-z", "--no-renames", before, after)
    if result.returncode:
        raise ValueError("Unable to compare upstream commits")
    return [name.decode("utf-8") for name in result.stdout.split(b"\0") if name], False


def write_github_output(path: Path, plan: dict[str, bool]) -> None:
    with path.open("a", encoding="utf-8") as output:
        for hand, enabled in plan.items():
            output.write(f"{hand}={str(enabled).lower()}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    parser.add_argument("--github-summary", type=Path)
    args = parser.parse_args()

    if args.repository != SOURCE_REPOSITORY or args.ref != SOURCE_REF:
        raise ValueError("Unexpected upstream repository or branch")
    changed, full = changed_files(args.checkout, args.before, args.after)
    plan = classify_paths(changed, full=full)
    write_github_output(args.github_output, plan)
    chosen = [hand for hand in ("github", "gitlab", "coolify") if plan[hand]]
    report = {
        "upstream": SOURCE_REPOSITORY,
        "revision": args.after,
        "full_refresh": full,
        "changed_paths": len(changed),
        "hands": chosen,
    }
    print(json.dumps(report, ensure_ascii=False))
    if args.github_summary:
        with args.github_summary.open("a", encoding="utf-8") as output:
            output.write(
                "### AI Agent Workflow routing\n"
                f"Source: {SOURCE_REPOSITORY} at {args.after}\n\n"
                f"Changed paths: {len(changed)}; conservative full refresh: {full}\n\n"
                f"Selected Hands: {', '.join(chosen) or 'none'}\n\n"
                "This receiver does not deploy or merge unapproved MCP source changes.\n"
            )


if __name__ == "__main__":
    main()
