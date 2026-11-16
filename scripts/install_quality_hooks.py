"""Install tracked quality gates; never push or rewrite user commits."""

import os
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    git = shutil.which("git")
    if git is None:
        raise SystemExit("Git is required.")
    hooks = root / ".githooks"
    for name in ("pre-commit", "pre-push"):
        hook = hooks / name
        if not hook.is_file() or not os.access(hook, os.X_OK):
            raise SystemExit(
                f"Missing or non-executable tracked hook: {hook}. "
                "Refusing to configure an empty hooksPath."
            )
    configured = subprocess.run(  # noqa: S603 -- fixed local Git config read
        [git, "config", "--get", "core.hooksPath"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if configured and configured != ".githooks":
        raise SystemExit(f"Existing hooksPath {configured!r}: refusing to replace unrelated hooks.")
    subprocess.run(  # noqa: S603 -- fixed local hooksPath, no external side effect
        [git, "config", "--local", "core.hooksPath", ".githooks"], cwd=root, check=True
    )
    print("Installed pre-commit (staged) and pre-push (outgoing refs) quality gates.")


if __name__ == "__main__":
    main()
