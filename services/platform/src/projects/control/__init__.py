"""Resolve the same owner's canonical Control modules in a source checkout."""

from pathlib import Path

# Images copy the canonical package over this checkout-only package entry point.
# Extend only Control; the selected projects/common/teams roots stay unchanged.
_canonical = Path(__file__).resolve().parents[4] / "projects" / "control"
if _canonical.is_dir():
    __path__.append(str(_canonical))
