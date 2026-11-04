from __future__ import annotations

from pathlib import Path


def read_secret(value: str, file_path: Path | None, *, setting_name: str) -> str:
    """Resolve one explicit secret source without exposing its contents."""
    if value and file_path is not None:
        raise ValueError(f"configure only {setting_name} or {setting_name}_FILE")
    if file_path is None:
        return value.strip()
    try:
        return file_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ValueError(f"cannot read {setting_name}_FILE") from error
