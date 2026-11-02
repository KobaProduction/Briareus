"""Kill every process belonging to this worker's isolated execution UID."""

import os
import signal
from pathlib import Path


def kill_execution_processes(execution_uid: int) -> None:
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = dict(
                line.split(":", 1)
                for line in (entry / "status").read_text().splitlines()
                if ":" in line
            )
            if int(fields["Uid"].split()[0]) == execution_uid:
                os.kill(int(entry.name), signal.SIGKILL)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
