"""Load operator-owned native Serena configuration without installing tools."""

import os
import shutil
import stat
from pathlib import Path


def prepare_home(workspace: Path, home: Path, *, required: bool) -> None:
    source = workspace / "toolchains" / "serena" / "serena_config.yml"
    if not source.is_file():
        if required:
            raise ValueError(
                "Shared Serena tools are not provisioned. Ask the operator to install "
                "language servers and create toolchains/serena/serena_config.yml through "
                "the administrative Server terminal; agents must not install them."
            )
        return
    validate_operator_ownership(workspace, source)
    shutil.copyfile(source, home / "serena_config.yml")


def validate_operator_ownership(workspace: Path, config: Path) -> None:
    if os.name != "posix":
        return
    root = workspace.stat()
    if root.st_uid != 0 or (os.access(workspace, os.W_OK) and not root.st_mode & stat.S_ISVTX):
        raise ValueError(
            "The operator must protect the Server mount root with root ownership and a sticky bit."
        )
    for path in (workspace / "toolchains", config.parent, config):
        if path.stat().st_uid != 0 or os.access(path, os.W_OK):
            raise ValueError(
                "Shared toolchains must be operator-owned and read-only to the Serena runtime."
            )
