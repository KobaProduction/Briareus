# MCP module catalog and source ownership — V2

Every MCP capability is independently packaged under Hands with its owner source, Dockerfile/Compose, dependency/lock and health/start contract. Nodes select installed/running module sets; the presence of a source directory does not imply a deployed endpoint or a stable public URL.

| MCP family | Source tree in the current checkout | Technical contract |
| --- | --- | --- |
| Files | hands/files/ | [Files](files/README.md) |
| Terminal | hands/terminal/ | [Terminal](terminal/README.md) |
| Browser/Web | hands/web/ | [Browser/Web](web/README.md) |
| GitHub/GitLab provider SVC | hands/svc/ | [SVC](svc/README.md) |
| Reverse / program analysis | hands/reverse/, hands/radare2/ | [Reverse](reverse/README.md) |
| Infrastructure Hand | hands/infrastructure/ | [Infrastructure](infrastructure/README.md) |
| Semantic code tooling | hands/serena/ | [Hand runtime and provider policy](../shared/hand-runtime-capabilities.md) |

The target is **one module catalog directory per capability**, optionally grouped, and independently selected module deployments. Do not copy module source separately for each Node instance or merge unrelated provider tools into one endpoint.

All module invocations are tied to a trusted Node UUID, logical Project UUID and active AgentSession. Node Gateway checks admission; the owning module checks the exact effect/resource through Node Access. Connected deployments enforce explicitly configured OAuth audiences. Standalone mode may omit MCP OAuth but **never** Project isolation or session/effect policy. A module catalog entry, friendly name or caller-supplied file path is not authority.

Build and rollout owners must separately inspect current services/, hands/, generated Compose and approved Development settings. Source targets are not live deployment evidence. See [package boundaries](../shared/README.md) and [deployment](../operations/README.md).
