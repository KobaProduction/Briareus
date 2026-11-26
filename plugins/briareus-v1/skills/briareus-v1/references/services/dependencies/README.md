# Briareus V1 Dependencies

Stable PostgreSQL, Valkey and persistent Chromium lifecycle. ZITADEL and the existing Ghidra MCP deployment are external. Dependencies does not build or start Ghidra workers or an MCP bridge.

Deploy this owner with `docker-compose.yaml` or the generated
`docker-compose.coolify.yaml`. Use the common environment Destination/network.

Chromium has a configurable `/dev/shm` tmpfs capacity (`CHROMIUM_SHM_SIZE`,
4 GiB by default). It is a ceiling, not preallocated RAM; memory used here
counts toward the Chromium cgroup budget. The installed Debian Chromium
launcher falls back to temporary files when available shared memory is below
its threshold (approximately 3.8 GiB in the current package). Keep sufficient
capacity on the node, and verify the effective mount size and launch flags
after recreating the Chromium container. Persistent profile and download
volumes remain unchanged.
