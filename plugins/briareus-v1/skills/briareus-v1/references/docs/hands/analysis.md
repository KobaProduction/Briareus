# Analysis Hands — radare2 and Ghidra

**Catalog:** `analysis` (Analyzer-R), `analysis-g` (Analyzer G), `radare2`, `ghidra`. The four names are four distinct deployable Hands, not one legacy analysis service.

| Hand | Responsibility | Source |
| --- | --- | --- |
| Analyzer-R (`analysis`) | Proxy/unified analysis interface over native radare2 | [README](../../services/hands/analysis/README.md) |
| Analyzer G (`analysis-g`) | Provider-neutral Ghidra-backed analysis facade | [README](../../services/hands/analysis-g/README.md) |
| radare2 (`radare2`) | Native radare2 tool engine | [README](../../services/hands/radare2/README.md) |
| Ghidra (`ghidra`) | Briareus adapter to a separately deployed Ghidra MCP | [README](../../services/hands/ghidra/README.md) |

Analyzer-R and radare2 are separate deployments. The native radare2 engine requires `open_file` before file-dependent operations; an early `list_files` rejection is caller state and retains an MCP error response, not a process failure. The proxy must not duplicate an alert already classified by the backend.

The existing external Ghidra MCP engine and its project database are outside the Briareus application source and shared Server files. Configure actual reachable upstream URLs; do not create a second Ghidra engine or infer availability from a running facade. Source catalog and discovered live MCP paths are authoritative; native Hand `/mcp` routes and Gateway public endpoints are distinct.

See [MCP connections](../mcp-connections.md) and [deployment](../operations/deployment.md).
