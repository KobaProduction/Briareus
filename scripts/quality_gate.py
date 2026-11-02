"""Local quality entry point; dependencies are isolated from service runtimes."""

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    command = [
        "uv",
        "run",
        "--project",
        str(root / "scripts/quality"),
        "--frozen",
        "python",
        str(root / "scripts/quality/main.py"),
        *sys.argv[1:],
    ]
    return subprocess.run(command, cwd=root, check=False).returncode  # noqa: S603 -- pinned gate argv


if __name__ == "__main__":
    raise SystemExit(main())
