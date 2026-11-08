# Briareus V1 / Serena

Semantic code navigation and refactoring over Server workspace folders. Register project_id and folder through MCP or SERENA_PROJECTS; each project receives its own stdio process and private Serena state. Process count and idle closure are configurable. No per-project container or network port is created.

The service uses the node private network, standard telemetry and the same external OIDC authorization as other hands.
