# External Ghidra MCP

Ghidra MCP is the external analysis system built from the repository and revision
in `source.json`. `fetch_source.py` validates and fetches that exact revision.

- `ghidra-engine`: Java/Ghidra engine, internal port 8089.
- `ghidra-mcp`: the external MCP bridge, internal port 8081.

The two containers form one Ghidra MCP dependency. They import no Briareus
application or shared source. Our configurable adapter lives separately under
`services/hands/ghidra`; Analysis uses its private interface and the MCP upload URL.
Persistent data/project/artifact volumes retain their existing identities.
