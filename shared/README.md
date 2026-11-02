# Focused shared contracts and capabilities

Share actually reused functionality through small stable packages with
explicit owners/consumers. Infrastructure, Node and MCP modules import and
watch only required package paths, never all shared code by default.

Keep typed DTOs, transport and reusable capabilities at their lowest valid
owner. Do not distribute another service's ORM, universal business model,
human credential authority or duplicated Cedar policy through shared.
Internal domain/application dependencies still point inward.

Module-specific Files/Terminal/Analysis application scenarios do not belong
in a universal `project_runtime_client`. Put them with their owner; share
only mechanisms/types actually reused by declared consumers. Remove obsolete
implementations and compatibility paths after resolving static, dynamic and
build consumers. Tests exclusive to removed legacy contracts are removed
with them; applicable invariant coverage remains. See the
[responsibility map](../docs/shared/runtime-module-boundaries.md#decomposition-of-runtime-clients).

gRPC/WSS adapters reuse one Protobuf contract and application use cases.
Shared code does not grant access or make catalog presence callable.
See [topology](../docs/architecture/infrastructure-hands-shared.md) and
[engineering rules](../docs/architecture/engineering-requirements.md).
