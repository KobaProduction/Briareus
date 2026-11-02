"""Project/Resource owner namespace: no eager cross-owner domain import.

Control owns Project/InvalidOwnership; Catalog owns resource vocabulary.
Loading one owner-specific module never forces the other's domain/source.
Public names remain import-compatible with the accepted source release.
"""

from __future__ import annotations

from importlib import import_module as import_module
from typing import TYPE_CHECKING

from project_runtime_client._lazy_exports import _LazyOwnerExports

_OWNER_PUBLIC_EXPORTS: dict[str, tuple[str, str]] = {
    "Project": ("projects._domain", "Project"),
    "InvalidOwnership": ("projects._domain", "InvalidOwnership"),
    "AmbiguousResource": ("projects._resource_domain", "AmbiguousResource"),
    "EffectiveResource": ("projects._resource_domain", "EffectiveResource"),
    "OwnerScope": ("projects._resource_domain", "OwnerScope"),
    "ResourceKind": ("projects._resource_domain", "ResourceKind"),
    "ResourceOwner": ("projects._resource_domain", "ResourceOwner"),
    "ResourceScope": ("projects._resource_domain", "ResourceScope"),
}
if TYPE_CHECKING:
    from ._domain import InvalidOwnership, Project
    from ._resource_domain import (
        AmbiguousResource,
        EffectiveResource,
        OwnerScope,
        ResourceKind,
        ResourceOwner,
        ResourceScope,
    )

__all__ = [
    "AmbiguousResource",
    "EffectiveResource",
    "InvalidOwnership",
    "OwnerScope",
    "Project",
    "ResourceKind",
    "ResourceOwner",
    "ResourceScope",
]


_owner_exports = _LazyOwnerExports(__name__, _OWNER_PUBLIC_EXPORTS, __all__)
__getattr__ = _owner_exports.resolve
__dir__ = _owner_exports.names
del _LazyOwnerExports, _owner_exports
