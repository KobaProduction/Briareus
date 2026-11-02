"""Resolve only this owner's canonical Catalog modules in a source checkout."""

from pathlib import Path

# Images replace this source-layout entry point with the canonical package.
_canonical = Path(__file__).resolve().parents[4] / "projects" / "catalog"
if _canonical.is_dir():
    __path__.append(str(_canonical))
