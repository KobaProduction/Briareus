"""Optional isolated terminal read-only metadata owner stage; not deployed."""

from pathlib import Path

from starlette.applications import Starlette

from hand_runtime import TrustedMetadataPorts, build_protected_metadata_app


def build_protected_terminal_metadata_app(ports: TrustedMetadataPorts) -> Starlette:
    """Require true signed Project/Cedar/owner inspection, no legacy provider."""
    return build_protected_metadata_app(
        hand="terminal",
        source_root=Path(__file__).resolve().parents[1],
        ports=ports,
    )
