"""Public Hand exports, loaded only when the corresponding adapter is requested.

Pure process authority can be imported without HTTP/MCP/provider dependencies.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._catalog import discover_source_tools, source_capabilities
    from ._diagnostics import ProtectedHandTools
    from ._effect_auth import (
        EffectAuthorizationMiddleware,
        EffectResolver,
        PrivateDecisionReply,
        ResolvedEffect,
        ResourceTrust,
        ToolEffectBinding,
        TrustedPrivateDecisionPort,
    )
    from ._hand_app import create_diagnostic_hand_app
    from ._owner_metadata import (
        MetadataInspection,
        ResourceMetadata,
        TrustedMetadataPorts,
        build_protected_metadata_app,
    )

__all__ = [
    "EffectAuthorizationMiddleware",
    "EffectResolver",
    "MetadataInspection",
    "PrivateDecisionReply",
    "ProtectedHandTools",
    "ResolvedEffect",
    "ResourceMetadata",
    "ResourceTrust",
    "ToolEffectBinding",
    "TrustedMetadataPorts",
    "TrustedPrivateDecisionPort",
    "build_protected_metadata_app",
    "create_diagnostic_hand_app",
    "discover_source_tools",
    "source_capabilities",
]


def __getattr__(name: str) -> object:
    match name:
        case "discover_source_tools":
            from ._catalog import discover_source_tools

            return discover_source_tools
        case "source_capabilities":
            from ._catalog import source_capabilities

            return source_capabilities
        case "ProtectedHandTools":
            from ._diagnostics import ProtectedHandTools

            return ProtectedHandTools
        case "create_diagnostic_hand_app":
            from ._hand_app import create_diagnostic_hand_app

            return create_diagnostic_hand_app
        case _:
            return _security_export(name)


def _security_export(name: str) -> object:
    match name:
        case "EffectAuthorizationMiddleware":
            from ._effect_auth import EffectAuthorizationMiddleware

            return EffectAuthorizationMiddleware
        case "EffectResolver":
            from ._effect_auth import EffectResolver

            return EffectResolver
        case "PrivateDecisionReply":
            from ._effect_auth import PrivateDecisionReply

            return PrivateDecisionReply
        case "ResolvedEffect":
            from ._effect_auth import ResolvedEffect

            return ResolvedEffect
        case "ResourceTrust":
            from ._effect_auth import ResourceTrust

            return ResourceTrust
        case "ToolEffectBinding":
            from ._effect_auth import ToolEffectBinding

            return ToolEffectBinding
        case "TrustedPrivateDecisionPort":
            from ._effect_auth import TrustedPrivateDecisionPort

            return TrustedPrivateDecisionPort
        case _:
            return _metadata_export(name)


def _metadata_export(name: str) -> object:
    match name:
        case "MetadataInspection":
            from ._owner_metadata import MetadataInspection

            return MetadataInspection
        case "ResourceMetadata":
            from ._owner_metadata import ResourceMetadata

            return ResourceMetadata
        case "TrustedMetadataPorts":
            from ._owner_metadata import TrustedMetadataPorts

            return TrustedMetadataPorts
        case "build_protected_metadata_app":
            from ._owner_metadata import build_protected_metadata_app

            return build_protected_metadata_app
        case _:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
