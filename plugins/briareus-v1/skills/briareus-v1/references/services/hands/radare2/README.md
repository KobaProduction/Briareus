# Briareus V1 / radare2

Direct native radare2 MCP engine, independently deployed with the shared Server workspace. Analyzer provides the separate proxy surface.

The native engine requires `open_file` before `list_files` and other file-dependent
operations. Its `-32611` rejection on `list_files` is a caller-state warning,
not a process failure. Other engine/transport failures remain errors.
