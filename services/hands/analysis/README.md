# Briareus V1 / Analyzer-R

Independent forwarding layer over the radare2 MCP hand. RADARE2_MCP_URL selects its private backend; the native engine is deployed separately.

When the native radare2 engine rejects `list_files` before `open_file`, the
proxy preserves the tool error for the caller and records it below warning
severity to avoid a second alert. The public proxy owns the invocation audit.
